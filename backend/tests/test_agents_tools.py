from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domains.agents.errors import (
    AgentToolLimitError,
    AgentToolRegistrationError,
    AgentToolValidationError,
)
from app.domains.agents.tools import (
    Tool,
    ToolDataType,
    ToolDefinition,
    ToolInputContract,
    ToolMetadata,
    ToolOutputContract,
    ToolParameter,
    ToolPolicyMetadata,
    ToolRegistry,
    ToolRegistryLimits,
    ToolRiskLevel,
    ToolState,
)


def make_definition(
    tool_id: str = "deployment.lookup",
    *,
    state: ToolState = ToolState.enabled,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        metadata=ToolMetadata(
            display_name="Deployment Lookup",
            description="Describes deployment information without executing an action.",
            version="1.0.0",
            category="knowledge",
            capabilities=("read", "deterministic"),
            state=state,
            policy=ToolPolicyMetadata(
                risk_level=ToolRiskLevel.low,
                requires_approval=False,
                permission_scopes=("knowledge.read",),
                policy_tags=("read-only",),
            ),
        ),
        input_contract=ToolInputContract(
            fields=(
                ToolParameter(
                    name="environment",
                    data_type=ToolDataType.string,
                    required=True,
                ),
            )
        ),
        output_contract=ToolOutputContract(
            fields=(
                ToolParameter(
                    name="status",
                    data_type=ToolDataType.string,
                    required=True,
                ),
            )
        ),
    )


def test_tool_definition_preserves_typed_contract_and_metadata() -> None:
    definition = make_definition()

    assert definition.tool_id == "deployment.lookup"
    assert definition.metadata.category == "knowledge"
    assert definition.metadata.capabilities == ("deterministic", "read")
    assert definition.metadata.policy.permission_scopes == ("knowledge.read",)
    assert definition.input_contract.fields[0].required is True
    assert definition.output_contract.fields[0].data_type == ToolDataType.string


def test_invalid_tool_definition_and_contracts_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolDefinition(
            tool_id="Invalid Tool",
            metadata=make_definition().metadata,
            input_contract=make_definition().input_contract,
            output_contract=make_definition().output_contract,
        )

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        ToolMetadata(
            display_name="Tool",
            description="Description",
            version="1.0.0",
            category="custom",
            capabilities=("read", "read"),
        )

    with pytest.raises(ValidationError, match="array parameters"):
        ToolParameter(name="items", data_type=ToolDataType.array)

    with pytest.raises(ValidationError, match="contract fields"):
        ToolInputContract(
            fields=(
                ToolParameter(name="value", data_type=ToolDataType.string),
                ToolParameter(name="value", data_type=ToolDataType.string),
            )
        )


def test_registry_registers_lookup_and_existence_are_explicit() -> None:
    registry = ToolRegistry()
    definition = make_definition()

    assert registry.register(definition) == definition
    assert registry.get(definition.tool_id) == definition
    assert registry.exists(definition.tool_id) is True
    assert registry.get("missing.tool") is None
    assert registry.exists("missing.tool") is False
    assert registry.count == 1


def test_duplicate_registration_is_rejected() -> None:
    definition = make_definition()
    registry = ToolRegistry([definition])

    with pytest.raises(AgentToolRegistrationError, match="already registered"):
        registry.register(definition)


def test_listing_is_deterministic_and_supports_discovery_filters() -> None:
    registry = ToolRegistry(
        [
            make_definition("zeta.tool"),
            make_definition("alpha.tool"),
            make_definition("disabled.tool", state=ToolState.disabled),
        ]
    )

    assert [tool.tool_id for tool in registry.list_tools()] == ["alpha.tool", "zeta.tool"]
    assert [tool.tool_id for tool in registry.discover_tools(include_disabled=True)] == [
        "alpha.tool",
        "disabled.tool",
        "zeta.tool",
    ]
    assert [tool.tool_id for tool in registry.list_tools(category="knowledge")] == [
        "alpha.tool",
        "zeta.tool",
    ]
    assert [tool.tool_id for tool in registry.list_tools(capability="read")] == [
        "alpha.tool",
        "zeta.tool",
    ]


class DescribedTool:
    definition = make_definition("descriptor.tool")


def test_read_only_tool_protocol_is_compatible_without_execution() -> None:
    descriptor = DescribedTool()

    assert isinstance(descriptor, Tool)
    registry = ToolRegistry([descriptor])

    assert registry.get("descriptor.tool") == descriptor.definition
    assert not hasattr(descriptor, "execute")


def test_empty_registry_and_invalid_lookup_are_safe() -> None:
    registry = ToolRegistry()

    assert registry.count == 0
    assert registry.list_tools() == ()
    with pytest.raises(AgentToolValidationError, match="stable identifier"):
        registry.get("Invalid Tool")


def test_registry_limits_are_enforced() -> None:
    with pytest.raises(AgentToolLimitError, match="maximum size"):
        ToolRegistry(
            [make_definition("one.tool"), make_definition("two.tool")],
            limits=ToolRegistryLimits(max_tools=1),
        )

    with pytest.raises(AgentToolLimitError, match="too many capabilities"):
        ToolRegistry(
            [make_definition()],
            limits=ToolRegistryLimits(max_capabilities_per_tool=1),
        )
