from typing import List, Optional

import pytest
from pydantic import BaseModel

from mountaineer.client_builder.parser import ControllerParser
from mountaineer.controller import ControllerBase
from mountaineer.render import RenderBase


# Define base models for inheritance
class PersonBase(BaseModel):
    name: str
    age: int


class EmployeeBase(BaseModel):
    employee_id: str
    department: str


# Define a model with multiple inheritance
class EmployeePerson(PersonBase, EmployeeBase):
    position: str
    salary: float


# Define a model that inherits from the multiple inheritance model
class Manager(EmployeePerson):
    team_size: int
    reports_to: Optional[str] = None


# Define a render response that uses the models with multiple inheritance
class EmployeeRender(RenderBase):
    employees: List[EmployeePerson]
    managers: List[Manager]


# Define a controller that uses these models
class EmployeeController(ControllerBase):
    url = "/employees"
    view_path = "/employees.tsx"

    async def render(self) -> EmployeeRender:
        return EmployeeRender(employees=[], managers=[])


class TestTypeScriptGenerationWithMultipleInheritance:
    @pytest.fixture
    def parser(self):
        return ControllerParser()

    def test_typescript_generation_with_multiple_inheritance(self, parser):
        """Test that TypeScript generation works correctly for models with multiple inheritance in a real-world scenario"""
        # Parse the models
        person_base_wrapper = parser._parse_model(PersonBase)
        employee_base_wrapper = parser._parse_model(EmployeeBase)
        employee_person_wrapper = parser._parse_model(EmployeePerson)
        manager_wrapper = parser._parse_model(Manager)

        # Import the ModelInterface class
        from mountaineer.client_builder.interface_builders.model import ModelInterface

        # Generate TypeScript interfaces
        person_base_interface = ModelInterface.from_model(person_base_wrapper)
        employee_base_interface = ModelInterface.from_model(employee_base_wrapper)
        employee_person_interface = ModelInterface.from_model(employee_person_wrapper)
        manager_interface = ModelInterface.from_model(manager_wrapper)

        # Convert to TypeScript code
        person_base_ts = person_base_interface.to_js()
        employee_base_ts = employee_base_interface.to_js()
        employee_person_ts = employee_person_interface.to_js()
        manager_ts = manager_interface.to_js()

        # Print the generated TypeScript code for debugging
        print(f"PersonBase TypeScript:\n{person_base_ts}\n")
        print(f"EmployeeBase TypeScript:\n{employee_base_ts}\n")
        print(f"EmployeePerson TypeScript:\n{employee_person_ts}\n")
        print(f"Manager TypeScript:\n{manager_ts}\n")

        # Check that the inheritance hierarchy is correct
        assert "interface PersonBase" in person_base_ts
        assert "interface EmployeeBase" in employee_base_ts
        assert (
            "interface EmployeePerson extends PersonBase, EmployeeBase"
            in employee_person_ts
        )
        assert "interface Manager extends EmployeePerson" in manager_ts

        # Check that fields are correctly included
        assert "name: string" in person_base_ts
        assert "age: number" in person_base_ts
        assert "employee_id: string" in employee_base_ts
        assert "department: string" in employee_base_ts
        assert "position: string" in employee_person_ts
        assert "salary: number" in employee_person_ts
        assert "team_size: number" in manager_ts
        assert "reports_to?: string" in manager_ts

        # Check that the inheritance hierarchy is correct
        # PersonBase and EmployeeBase should not extend anything
        assert "extends" not in person_base_ts
        assert "extends" not in employee_base_ts

        # EmployeePerson should extend both PersonBase and EmployeeBase
        assert "extends PersonBase, EmployeeBase" in employee_person_ts

        # Manager should extend EmployeePerson
        assert "extends EmployeePerson" in manager_ts
