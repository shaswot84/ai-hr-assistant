from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.identity import Department, Designation, Employee, Person


class DepartmentRepo:
    """Data access for department rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, department: Department) -> Department:
        """Persist a new department and flush to obtain its generated id."""
        self._db.add(department)
        await self._db.flush()
        return department

    async def get(self, department_id: uuid.UUID) -> Department | None:
        """Fetch a department by id, or None if it does not exist."""
        return await self._db.get(Department, department_id)

    async def get_by_name(self, name: str) -> Department | None:
        """Fetch a department by its unique name, or None."""
        stmt = select(Department).where(Department.name == name.strip())
        return await self._db.scalar(stmt)

    async def list_all(self) -> list[Department]:
        """List all departments alphabetically."""
        stmt = select(Department).order_by(Department.name)
        res = await self._db.scalars(stmt)
        return list(res)


class DesignationRepo:
    """Data access for designation rows (job titles within a department)."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, designation: Designation) -> Designation:
        """Persist a new designation and flush to obtain its generated id."""
        self._db.add(designation)
        await self._db.flush()
        return designation

    async def get(self, designation_id: uuid.UUID) -> Designation | None:
        """Fetch a designation by id, or None if it does not exist."""
        return await self._db.get(Designation, designation_id)

    async def get_by_department_title(self, department_id: uuid.UUID, title: str) -> Designation | None:
        """Fetch a designation by (department, title), or None (duplicate guard)."""
        stmt = select(Designation).where(
            Designation.department_id == department_id,
            Designation.title == title.strip(),
        )
        return await self._db.scalar(stmt)

    async def list_all(self) -> list[Designation]:
        """List all designations, ordered by title."""
        stmt = select(Designation).order_by(Designation.title)
        res = await self._db.scalars(stmt)
        return list(res)

    async def list_for_department(self, department_id: uuid.UUID) -> list[Designation]:
        """List the designations of one department, seniority level first."""
        stmt = (
            select(Designation)
            .where(Designation.department_id == department_id)
            .order_by(Designation.level, Designation.title)
        )
        res = await self._db.scalars(stmt)
        return list(res)


class EmployeeRepo:
    """Data access for employee rows (and their Person rows where needed)."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, employee: Employee) -> Employee:
        """Persist a new employee and flush to obtain its generated id."""
        self._db.add(employee)
        await self._db.flush()
        return employee

    async def get(self, employee_id: uuid.UUID) -> Employee | None:
        """Fetch an employee by id, or None if it does not exist."""
        stmt = (
            select(Employee)
            .options(selectinload(Employee.person))
            .where(Employee.employee_id == employee_id)
        )
        return await self._db.scalar(stmt)

    async def get_by_code(self, employee_code: str) -> Employee | None:
        """Fetch an employee by their unique employee code, or None."""
        stmt = (
            select(Employee)
            .options(selectinload(Employee.person))
            .where(Employee.employee_code == employee_code.strip())
        )
        return await self._db.scalar(stmt)

    async def find_by_person_id(self, person_id: uuid.UUID) -> Employee | None:
        """Return the Employee row for a person id, or None (used by the hire handoff)."""
        stmt = (
            select(Employee)
            .options(selectinload(Employee.person))
            .where(Employee.person_id == person_id)
        )
        return await self._db.scalar(stmt)

    async def list(
        self,
        *,
        search: str | None = None,
        department_id: uuid.UUID | None = None,
        employment_status: str | None = None,
    ) -> list[Employee]:
        """List employees, optionally filtered by name/email/code search,
        department, or employment status. Ordered by name.
        """
        stmt = (
            select(Employee)
            .options(selectinload(Employee.person))
            .join(Person, Person.person_id == Employee.person_id)
        )
        if search:
            like = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Person.first_name.ilike(like),
                    Person.last_name.ilike(like),
                    Person.email.ilike(like),
                    Employee.employee_code.ilike(like),
                )
            )
        if department_id is not None:
            stmt = stmt.where(Employee.department_id == department_id)
        if employment_status is not None:
            stmt = stmt.where(Employee.employment_status == employment_status)
        stmt = stmt.order_by(Person.first_name, Person.last_name)
        res = await self._db.scalars(stmt)
        return list(res)

    async def save(self, employee: Employee) -> None:
        """Flush pending changes to an existing employee row."""
        await self._db.flush()

