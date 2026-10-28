import re
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.database import Base
from app.database.models import (
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    Organization,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    User,
)
from app.database.session import get_db
from app.services.payroll_parameters import load_parameters, resolve_parameters
from app.web.configuration import router as configuration_router
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


def csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_configuration_and_calculation(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'configuration.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        demo = seed(db)
        org_id, company_id = demo['organization'].id, demo['company'].id
        other = Organization(name='Otra', slug='otra')
        db.add(other)
        db.flush()
        other_id = other.id
        db.add(User(organization_id=other_id, email='other@example.com', password_hash=hash_password('other'), role='admin'))
        db.add(User(organization_id=org_id, email='viewer@example.com', password_hash=hash_password('viewer'), role='viewer'))
        db.add(NormativeParameter(code='web_rate', value=Decimal('1'), valid_from=date(2026, 1, 1)))
    app = FastAPI()
    app.include_router(router)
    app.include_router(configuration_router)
    app.state.payroll_data_source = SqlAlchemyDataSource(factory)
    app.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=True, secret_key='configuration-test')
    def session() -> Generator[Session, None, None]:
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        def login(email: str, password: str) -> str:
            page = client.get('/login')
            assert client.post('/login', data={'email': email, 'password': password, 'csrf_token': csrf(page.text)}, follow_redirects=False).status_code == 303
            page = client.get('/configuracion')
            assert page.status_code == 200, page.text
            return csrf(page.text)
        token = login('admin@example.com', 'admin')
        def post(action: str, fields: dict[str, str]):
            response = client.post('/configuracion/' + action, data={'csrf_token': token, **fields}, follow_redirects=False)
            assert response.status_code == 303, response.text
            assert 'error=' not in response.headers['location'], response.headers['location']
            return response
        assert client.post('/configuracion/concept', data={'code': 'X'}).status_code == 403
        post('concept', {'code': 'WEB_BONUS', 'name': 'Bono web', 'nature': 'REMUNERATIVE'})
        post('parameter', {'code': 'web_rate', 'value': '42', 'valid_from': '2026-01-01'})
        post('formula', {'code': 'WEB_BONUS', 'description': 'Bono', 'formula': '{"parameter":"web_rate"}', 'conditions': '[]', 'valid_from': '2026-01-01'})
        with factory() as db:
            formula = db.scalar(select(FormulaDefinition).where(FormulaDefinition.code == 'WEB_BONUS'))
            formula_id = formula.id
            assert db.scalar(select(FormulaVersion.status).where(FormulaVersion.formula_id == formula_id)) == 'DRAFT'
            assert resolve_parameters(load_parameters(db, date(2026, 6, 30), org_id))['web_rate'] == Decimal('42')
            assert resolve_parameters(load_parameters(db, date(2026, 6, 30), other_id))['web_rate'] == Decimal('1')
        post('validate', {'formula_id': str(formula_id)})
        post('approve', {'formula_id': str(formula_id)})
        post('concept', {'code': 'WEB_SAC_DED', 'name': 'Descuento SAC', 'nature': 'DEDUCTION'})
        post('formula', {'code': 'WEB_SAC_DED', 'formula': '{"variable":"settlement_gross"}', 'conditions': '[{"field":"run_type","operator":"eq","value":"SAC"}]', 'valid_from': '2026-01-01'})
        with factory() as db:
            special_id = db.scalar(select(FormulaDefinition.id).where(FormulaDefinition.code == 'WEB_SAC_DED'))
        post('validate', {'formula_id': str(special_id)})
        post('approve', {'formula_id': str(special_id)})
        post('version', {'formula_id': str(formula_id), 'formula': '{"constant":"99"}', 'conditions': '[]', 'valid_from': '2026-01-01'})
        with factory() as db:
            versions = db.scalars(select(FormulaVersion).where(FormulaVersion.formula_id == formula_id).order_by(FormulaVersion.version)).all()
            assert [v.status for v in versions] == ['APPROVED', 'DRAFT']
        created = client.post('/liquidaciones', data={'csrf_token': token, 'company_id': company_id, 'code': 'WEB-CFG', 'period_start': '2026-06-01', 'period_end': '2026-06-30', 'run_type': 'MONTHLY'}, follow_redirects=False)
        assert 'error=' not in created.headers['location']
        with factory() as db:
            run_id = db.scalar(select(PayrollRun.id).where(PayrollRun.code == 'WEB-CFG'))
        result = client.post(f'/liquidaciones/{run_id}/accion', data={'csrf_token': token, 'action': 'calculate'}, follow_redirects=False)
        assert 'error=' not in result.headers['location'], result.headers['location']
        with factory() as db:
            assert db.scalar(select(PayrollResult.id).where(PayrollResult.payroll_run_id == run_id)) is not None
            amounts = db.scalars(select(PayrollItem.amount).join(PayrollResult).where(PayrollResult.payroll_run_id == run_id, PayrollItem.code == 'WEB_BONUS')).all()
            assert amounts and all(amount == Decimal('42') for amount in amounts)
            own = db.scalar(select(NormativeParameter).where(NormativeParameter.organization_id == org_id, NormativeParameter.code == 'web_rate'))
            global_parameter = db.scalar(select(NormativeParameter).where(NormativeParameter.organization_id.is_(None), NormativeParameter.code == 'web_rate'))
            own_id, global_id = own.id, global_parameter.id
        denied = client.post('/configuracion/parameter_close', data={'csrf_token': token, 'parameter_id': global_id, 'valid_to': '2026-06-30'}, follow_redirects=False)
        assert 'error=' in denied.headers['location']
        post('parameter_close', {'parameter_id': str(own_id), 'valid_to': '2026-06-30'})
        post('parameter', {'code': 'web_rate', 'value': '45', 'valid_from': '2026-07-01'})
        with factory() as db:
            assert resolve_parameters(load_parameters(db, date(2026, 7, 1), org_id))['web_rate'] == Decimal('45')
        client.post('/logout', data={'csrf_token': token})
        token = login('viewer@example.com', 'viewer')
        assert client.post('/configuracion/parameter', data={'csrf_token': token}).status_code == 403
        client.post('/logout', data={'csrf_token': token})
        token = login('other@example.com', 'other')
        assert 'WEB_BONUS' not in client.get('/configuracion').text
        denied = client.post('/configuracion/approve', data={'csrf_token': token, 'formula_id': formula_id}, follow_redirects=False)
        assert 'error=' in denied.headers['location']


def test_parameter_organization_migration(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from app.config import get_settings

    url = f"sqlite:///{tmp_path / 'migration.sqlite'}"
    monkeypatch.setenv('PAYROLL_DATABASE_URL', url)
    get_settings.cache_clear()
    config = Config('alembic.ini')
    engine = create_engine(url)
    try:
        command.upgrade(config, 'j1a2b3c4d5e6')
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO normative_parameters (jurisdiction, code, agreement_code, category_code, value, valid_from, version) VALUES ('AR', 'X', '', '', 1, '2026-01-01', 1)"))
            connection.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (1, 'Uno', 'uno', '2026-01-01')"))
        command.upgrade(config, 'k1a2b3c4d5e6')
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO normative_parameters (organization_id, jurisdiction, code, agreement_code, category_code, value, valid_from, version) VALUES (1, 'AR', 'X', '', '', 2, '2026-01-01', 1)"))
            assert connection.scalar(text('SELECT COUNT(*) FROM normative_parameters')) == 2
        with pytest.raises(ValueError, match='parámetros de organizaciones'):
            command.downgrade(config, 'j1a2b3c4d5e6')
        with engine.begin() as connection:
            connection.execute(text('DELETE FROM normative_parameters WHERE organization_id IS NOT NULL'))
        command.downgrade(config, 'j1a2b3c4d5e6')
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_special_formula_validation_uses_run_type_contract() -> None:
    from app.api.formulas import _validate_candidate
    from app.core.payroll_engine.types import FormulaContext, FormulaDefinition

    context = FormulaContext(variables={}, parameters={}, concepts={}, functions={})
    definition = FormulaDefinition(code='APORTE', formula={'variable': 'settlement_gross'}, conditions=[{'field': 'run_type', 'operator': 'eq', 'value': 'SAC'}])
    assert _validate_candidate(definition, context, []) == []
    wrong = definition.model_copy(update={'conditions': [{'field': 'run_type', 'operator': 'eq', 'value': 'MONTHLY'}]})
    assert any('settlement_gross' in error for error in _validate_candidate(wrong, context, []))
    invalid = definition.model_copy(update={'conditions': [{'field': 'run_type', 'operator': 'eq', 'value': ['SAC']}]})
    assert _validate_candidate(invalid, context, [])
