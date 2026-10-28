from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.database.models import NormativeParameter
from app.services.payroll_parameters import load_parameters, parameter_snapshot, resolve_parameters


def test_effective_parameters_resolve_category_agreement_and_global() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for agreement, category, value in (
            ("", "", "1"), ("130/75", "", "2"),
            ("130/75", "ADMIN_A", "3"), ("389/04", "", "4"),
        ):
            session.add(NormativeParameter(
                code="rate", value=Decimal(value), agreement_code=agreement,
                category_code=category, valid_from=date(2026, 6, 1), valid_to=date(2026, 6, 30),
            ))
        session.commit()
        for day in (date(2026, 6, 1), date(2026, 6, 30)):
            rows = load_parameters(session, day)
            assert resolve_parameters(rows, "130/75", "ADMIN_A") == {"rate": Decimal("3")}
            assert resolve_parameters(rows, "130/75", "ADMIN_B") == {"rate": Decimal("2")}
            assert resolve_parameters(rows, "389/04", "ADMIN_A") == {"rate": Decimal("4")}
            assert resolve_parameters(rows, "unknown", "ADMIN_A") == {"rate": Decimal("1")}
            assert len(parameter_snapshot(rows)) == 4
            assert parameter_snapshot(rows)[2]["category_code"] == "ADMIN_A"
        assert load_parameters(session, date(2026, 7, 1)) == []
        session.add(NormativeParameter(
            code="rate", value=Decimal("99"), agreement_code="130/75",
            category_code="ADMIN_A", valid_from=date(2026, 6, 2),
        ))
        session.commit()
        with pytest.raises(ValueError, match="vigencias superpuestas"):
            resolve_parameters(load_parameters(session, date(2026, 6, 30)), "130/75", "ADMIN_A")
    engine.dispose()
