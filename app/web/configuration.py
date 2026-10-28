"""Configuration forms backed by the same handlers as the API."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.common import commit_or_conflict
from app.api.concepts import create_concept
from app.api.formulas import (
    FormulaScopeInput,
    approve_formula,
    create_formula,
    create_formula_version,
    set_formula_scope,
    validate_formula,
)
from app.api.schemas import ConceptInput, FormulaInput, FormulaVersionInput
from app.database.models import (
    AgreementCategory,
    AuditLog,
    CollectiveAgreement,
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    PayrollConcept,
)
from app.web.auth import enforce_csrf
from app.web.routes import (
    DataSource,
    SessionDep,
    SettingsDep,
    WebUserDep,
    _error_message,
    _render,
    _sql_user,
)

router: APIRouter = APIRouter()


def _redirect(request: Request, **params: str) -> RedirectResponse:
    return RedirectResponse(f"{request.url_for('configuration_list')}?{urlencode(params)}", status_code=303)


@router.get('/configuracion', name='configuration_list')
def configuration_list(request: Request, data: DataSource, user: WebUserDep, db: SessionDep, page: int = 1):
    if user.is_demo or getattr(data, 'is_demo', False):
        return _render(request, 'configuration/list.html', page_title='Configuración', active_nav='configuration', demo=True)
    actor = _sql_user(db, user, data, {'admin', 'editor', 'viewer'})
    page = max(1, page)
    offset = (page - 1) * 50
    concepts = db.scalars(select(PayrollConcept).where(PayrollConcept.organization_id == actor.organization_id).order_by(PayrollConcept.id).offset(offset).limit(51)).all()
    formulas = db.execute(select(FormulaDefinition, FormulaVersion).join(FormulaVersion, (FormulaVersion.formula_id == FormulaDefinition.id) & (FormulaVersion.version == FormulaDefinition.current_version)).where(FormulaDefinition.organization_id == actor.organization_id).order_by(FormulaDefinition.id).offset(offset).limit(51)).all()
    parameters = db.scalars(select(NormativeParameter).where(or_(NormativeParameter.organization_id.is_(None), NormativeParameter.organization_id == actor.organization_id)).order_by(NormativeParameter.id).offset(offset).limit(51)).all()
    agreements = db.scalars(select(CollectiveAgreement).order_by(CollectiveAgreement.code)).all()
    categories = db.execute(select(AgreementCategory, CollectiveAgreement.code).join(CollectiveAgreement, AgreementCategory.agreement_id == CollectiveAgreement.id).order_by(CollectiveAgreement.code, AgreementCategory.code)).all()
    return _render(request, 'configuration/list.html', page_title='Configuración', active_nav='configuration', demo=False,
                   concepts=concepts[:50], formulas=formulas[:50], parameters=parameters[:50], agreements=agreements, categories=categories,
                   page=page, has_next=max(len(concepts), len(formulas), len(parameters)) > 50, today=date.today().isoformat())


@router.post('/configuracion/{action}', name='configuration_action')
async def configuration_action(action: str, request: Request, data: DataSource, user: WebUserDep, db: SessionDep, settings: SettingsDep):
    form = await request.form()
    enforce_csrf(request, str(form.get('csrf_token', '')), settings, user.id)
    actor = _sql_user(db, user, data, {'admin'} if action in {'approve', 'parameter', 'parameter_close'} else {'admin', 'editor'})
    try:
        if action == 'concept':
            create_concept(ConceptInput(code=str(form.get('code', '')).strip(), name=str(form.get('name', '')).strip(), nature=form.get('nature'), description=str(form.get('description', '')) or None), db=db, user=actor)
            notice = 'Concepto creado.'
        elif action in {'formula', 'version'}:
            fields = dict(formula=json.loads(str(form.get('formula', ''))), conditions=json.loads(str(form.get('conditions', '[]')) or '[]'), depends_on=[x.strip() for x in str(form.get('depends_on', '')).split(',') if x.strip()], valid_from=form.get('valid_from'), valid_to=form.get('valid_to') or None)
            if form.get('rounding'):
                fields['rounding'] = json.loads(str(form['rounding']))
            if action == 'formula':
                result = create_formula(FormulaInput(code=str(form.get('code', '')).strip(), description=str(form.get('description', '')), **fields), db=db, user=actor)
                notice = 'Borrador creado.' + (' Advertencias: ' + '; '.join(result.warnings) if result.warnings else '')
            else:
                create_formula_version(int(str(form.get('formula_id', ''))), FormulaVersionInput(**fields), db=db, user=actor)
                notice = 'Nueva versión en borrador creada.'
        elif action in {'validate', 'approve', 'scope'}:
            formula_id = int(str(form.get('formula_id', '')))
            if action == 'scope':
                set_formula_scope(formula_id, FormulaScopeInput(agreement_code=str(form.get('agreement_code', '')) or None, category_code=str(form.get('category_code', '')) or None), db=db, user=actor)
                notice = 'Alcance actualizado.'
            else:
                (validate_formula if action == 'validate' else approve_formula)(formula_id, db=db, user=actor)
                notice = 'Fórmula validada.' if action == 'validate' else 'Fórmula aprobada.'
        elif action == 'parameter_close':
            row = db.scalar(select(NormativeParameter).where(NormativeParameter.id == int(str(form.get('parameter_id', ''))), NormativeParameter.organization_id == actor.organization_id))
            if row is None:
                raise HTTPException(status_code=404, detail='Parámetro de la organización no encontrado.')
            closing_end = date.fromisoformat(str(form.get('valid_to', '')))
            if closing_end < row.valid_from or (row.valid_to is not None and closing_end > row.valid_to):
                raise ValueError('El fin debe ser posterior al inicio y no puede extender una vigencia existente.')
            previous_end = row.valid_to.isoformat() if row.valid_to else None
            row.valid_to = closing_end
            db.add(AuditLog(organization_id=actor.organization_id, user_id=actor.id, action='parameter.closed', entity_type='NormativeParameter', entity_id=str(row.id), before={'valid_to': previous_end}, after={'valid_to': closing_end.isoformat()}))
            commit_or_conflict(db)
            notice = 'Vigencia cerrada. Ya puede crear el nuevo valor.'
        elif action == 'parameter':
            code = str(form.get('code', '')).strip()
            agreement = str(form.get('agreement_code', '')).strip()
            category = str(form.get('category_code', '')).strip()
            start = date.fromisoformat(str(form.get('valid_from', '')))
            end: date | None = date.fromisoformat(str(form.get('valid_to'))) if form.get('valid_to') else None
            value = Decimal(str(form.get('value', '')))
            exponent = value.as_tuple().exponent
            if not code or len(code) > 100 or not value.is_finite() or abs(value) >= Decimal('100000000000000') or (isinstance(exponent, int) and exponent < -4) or (end and end < start):
                raise ValueError('Código, valor o vigencia inválidos.')
            if agreement and db.scalar(select(CollectiveAgreement.id).where(CollectiveAgreement.code == agreement)) is None:
                raise ValueError('Convenio inexistente.')
            if category and (not agreement or db.scalar(select(AgreementCategory.id).join(CollectiveAgreement).where(CollectiveAgreement.code == agreement, AgreementCategory.code == category)) is None):
                raise ValueError('Categoría inexistente para el convenio.')
            overlap = select(NormativeParameter.id).where(NormativeParameter.organization_id == actor.organization_id, NormativeParameter.jurisdiction == 'AR', NormativeParameter.code == code, NormativeParameter.agreement_code == agreement, NormativeParameter.category_code == category, or_(NormativeParameter.valid_to.is_(None), NormativeParameter.valid_to >= start))
            if end:
                overlap = overlap.where(NormativeParameter.valid_from <= end)
            if db.scalar(overlap) is not None:
                raise ValueError('Ya existe un parámetro de la organización con vigencia superpuesta para ese alcance.')
            row = NormativeParameter(organization_id=actor.organization_id, jurisdiction='AR', code=code, agreement_code=agreement, category_code=category, value=value, valid_from=start, valid_to=end, version=1)
            db.add(row)
            db.flush()
            db.add(AuditLog(organization_id=actor.organization_id, user_id=actor.id, action='parameter.created', entity_type='NormativeParameter', entity_id=str(row.id), before=None, after={'code': code, 'value': str(value), 'agreement_code': agreement, 'category_code': category, 'valid_from': start.isoformat(), 'valid_to': end.isoformat() if end else None}))
            commit_or_conflict(db)
            notice = 'Parámetro de la organización creado.'
        else:
            raise HTTPException(status_code=404, detail='Acción desconocida.')
    except IntegrityError:
        db.rollback()
        return _redirect(request, error='Ya existe un registro con estos datos.')
    except (ValidationError, HTTPException, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        db.rollback()
        return _redirect(request, error=_error_message(exc))
    return _redirect(request, notice=notice)
