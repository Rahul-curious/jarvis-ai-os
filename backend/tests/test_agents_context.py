from __future__ import annotations

import asyncio
import uuid

import pytest

from app.domains.agents.context import (
    AgentConfigurationProvider,
    AgentContextAssembler,
    ContextBuilder,
    ContextProvider,
    ConversationHistoryProvider,
    KnowledgeContextProvider,
    MemoryContextProvider,
    RuntimeMetadataProvider,
    UserInformationProvider,
)
from app.domains.agents.errors import (
    AgentContextConfigurationError,
    AgentContextLimitError,
    AgentContextProviderError,
)
from app.domains.agents.schemas import (
    AgentConfiguration,
    ContextAssemblyRequest,
    ContextLimits,
    ContextSection,
    ConversationMessage,
    UserInformation,
)


def make_request(*, message_count: int = 2) -> ContextAssemblyRequest:
    user_id = uuid.uuid4()
    return (
        ContextBuilder()
        .with_run_id(uuid.uuid4())
        .with_user_id(user_id)
        .with_task("Summarize the deployment plan")
        .with_request_id("request-123")
        .with_conversation_history(
            [
                ConversationMessage(role="user", content=f"Message {index}")
                for index in range(message_count)
            ]
        )
        .with_runtime_metadata({"source": "test", "attempt": 1})
        .with_user_information(
            UserInformation(
                user_id=user_id,
                email="rahul@example.com",
                full_name="Rahul Prakash",
            )
        )
        .with_agent_configuration(
            AgentConfiguration(
                agent_key="assistant",
                agent_type="assistant",
                version="1.0",
                configuration={"mode": "test"},
            )
        )
        .build()
    )


def test_conversation_history_provider_returns_typed_messages() -> None:
    section = asyncio.run(ConversationHistoryProvider().build_context(make_request()))

    assert section.provider == "conversation_history"
    assert section.priority == ConversationHistoryProvider.priority
    assert section.data["message_count"] == 2
    assert section.data["messages"][0]["role"] == "user"


def test_runtime_metadata_provider_returns_runtime_values() -> None:
    section = asyncio.run(RuntimeMetadataProvider().build_context(make_request()))

    assert section.provider == "runtime_metadata"
    assert section.data["request_id"] == "request-123"
    assert section.data["metadata"] == {"source": "test", "attempt": 1}


def test_user_and_agent_providers_return_safe_typed_data() -> None:
    request = make_request()
    user_section = asyncio.run(UserInformationProvider().build_context(request))
    agent_section = asyncio.run(AgentConfigurationProvider().build_context(request))

    assert user_section.data["full_name"] == "Rahul Prakash"
    assert "password_hash" not in user_section.data
    assert agent_section.data["agent_key"] == "assistant"
    assert agent_section.data["configuration"] == {"mode": "test"}


def test_memory_and_knowledge_providers_are_extension_interfaces_only() -> None:
    assert MemoryContextProvider.name == "memory"
    assert KnowledgeContextProvider.name == "knowledge"
    assert MemoryContextProvider.__abstractmethods__ == {"build_context"}
    assert KnowledgeContextProvider.__abstractmethods__ == {"build_context"}


def test_assembler_registers_providers_and_merges_by_priority() -> None:
    assembler = AgentContextAssembler(providers=[])
    assembler.register_provider(ConversationHistoryProvider())
    assembler.register_provider(RuntimeMetadataProvider())
    assembler.register_provider(UserInformationProvider())
    assembler.register_provider(AgentConfigurationProvider())

    context = asyncio.run(assembler.build_context(make_request()))

    assert context.task == "Summarize the deployment plan"
    assert [section.provider for section in context.sections] == [
        "runtime_metadata",
        "user_information",
        "agent_configuration",
        "conversation_history",
    ]
    assert context.data["task"] == "Summarize the deployment plan"
    assert context.metadata.section_count == 4
    assert context.metadata.total_size_bytes > 0


class PriorityCollisionProvider(ContextProvider):
    name = "priority_collision"
    priority = 300

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        del request
        return ContextSection(
            provider=self.name,
            priority=self.priority,
            data={"task": "preferred"},
        )


def test_higher_provider_priority_wins_data_key_collisions() -> None:
    assembler = AgentContextAssembler()
    assembler.register_provider(PriorityCollisionProvider())

    context = asyncio.run(assembler.build_context(make_request()))

    assert context.data["task"] == "preferred"


def test_default_assembler_registers_all_required_concrete_providers() -> None:
    context = asyncio.run(AgentContextAssembler().build_context(make_request()))

    assert set(context.metadata.provider_names) == {
        "conversation_history",
        "runtime_metadata",
        "user_information",
        "agent_configuration",
    }


def test_duplicate_provider_registration_is_rejected() -> None:
    assembler = AgentContextAssembler(providers=[])
    assembler.register_provider(ConversationHistoryProvider())

    with pytest.raises(AgentContextConfigurationError, match="Duplicate context provider"):
        assembler.register_provider(ConversationHistoryProvider())


def test_missing_required_provider_is_rejected() -> None:
    assembler = AgentContextAssembler(providers=[ConversationHistoryProvider()])

    with pytest.raises(AgentContextConfigurationError, match="Required context providers"):
        asyncio.run(assembler.build_context(make_request()))


def test_context_limits_reject_large_history_and_large_sections() -> None:
    history_limits = ContextLimits(max_conversation_messages=1)
    with pytest.raises(AgentContextLimitError, match="message limit"):
        asyncio.run(
            AgentContextAssembler(limits=history_limits).build_context(make_request(message_count=2))
        )

    section_limits = ContextLimits(max_section_bytes=10, max_total_bytes=10)
    with pytest.raises(AgentContextLimitError, match="section size"):
        asyncio.run(
            AgentContextAssembler(limits=section_limits).build_context(make_request())
        )


class InvalidOutputProvider(ContextProvider):
    name = "invalid"
    priority = 90

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        del request
        return "invalid output"  # type: ignore[return-value]


class WrongPriorityProvider(ContextProvider):
    name = "wrong_priority"
    priority = 90

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        del request
        return ContextSection(provider=self.name, priority=91, data={"value": "bad"})


def test_invalid_provider_output_is_rejected() -> None:
    assembler = AgentContextAssembler(providers=[], required_provider_names=())
    assembler.register_provider(InvalidOutputProvider())

    with pytest.raises(AgentContextProviderError, match="invalid section"):
        asyncio.run(assembler.build_context(make_request()))


def test_provider_priority_must_match_registered_priority() -> None:
    assembler = AgentContextAssembler(providers=[], required_provider_names=())
    assembler.register_provider(WrongPriorityProvider())

    with pytest.raises(AgentContextProviderError, match="invalid priority"):
        asyncio.run(assembler.build_context(make_request()))
