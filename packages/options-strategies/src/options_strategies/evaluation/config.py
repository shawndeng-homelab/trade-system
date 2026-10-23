"""Explicit research assumptions for post-trade PMCC evaluation."""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator


class CostScenario(BaseModel):
    """Costs per contract per fill, and adverse option-price movement per share."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    name: str = Field(min_length=1)
    commission: float = Field(ge=0)
    slippage: float = Field(ge=0)


class EvaluationConfig(BaseModel):
    """Illustrative research scenarios, not estimates of a particular broker's fees."""

    model_config = ConfigDict(frozen=True)
    scenarios: tuple[CostScenario, ...] = (
        CostScenario(name="ideal", commission=0, slippage=0),
        CostScenario(name="reference", commission=0.65, slippage=0.01),
        CostScenario(name="stress", commission=1.30, slippage=0.05),
    )
    primary_scenario: str = "reference"
    time_segments: int = Field(3, ge=1, le=100)

    @model_validator(mode="after")
    def validate_scenarios(self):
        """Scenario names must be unique and include the displayed scenario."""
        names = [scenario.name for scenario in self.scenarios]
        if len(names) != len(set(names)):
            raise ValueError("Cost scenario names must be unique")
        if self.primary_scenario not in names:
            raise ValueError("primary_scenario must name a configured scenario")
        return self
