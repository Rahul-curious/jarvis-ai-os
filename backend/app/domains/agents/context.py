from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol

from pydantic import ValidationError

from app.domains.agents.errors import (
    AgentContextConfigurationError,
    AgentContextError,
    AgentContextLimitError,
    AgentContextProviderError,
    AgentValidationError,
)
from app.domains.agents.schemas import (
    AgentConfiguration,
    ContextAssemblyRequest,
    ContextLimits,
    ContextMetadata,
    ContextSection,
    ConversationMessage,
    ExecutionContext,
    UserInformation,
)

DEFAULT_CONTEXT_PROVIDER_NAMES = frozenset(
    {
        "conversation_history",
        "runtime_metadata",
        "user_information",
        "agent_configuration",
    }
)


def _json_size(value: Any, *, error_type: type[AgentContextError]) -> int:
    try:
        serialized = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise error_type("Context data must be JSON serializable") from exc
    return len(serialized.encode("utf-8"))


class ContextProvider(ABC):
    """Framework-neutral interface for one context source."""

    name: ClassVar[str]
    priority: ClassVar[int] = 100

    @abstractmethod
    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        """Build one validated section from the assembly request."""


class MemoryContextProvider(ContextProvider, ABC):
    """Extension interface reserved for future memory integration."""

    name = "memory"
    priority = 50


class KnowledgeContextProvider(ContextProvider, ABC):
    """Extension interface reserved for future RAG integration."""

    name = "knowledge"
    priority = 50


class ConversationHistoryProvider(ContextProvider):
    """Provides the conversation messages supplied by the caller."""

    name = "conversation_history"
    priority = 100

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        return ContextSection(
            provider=self.name,
            priority=self.priority,
            data={
                "messages": [
                    message.model_dump(mode="json") for message in request.conversation_history
                ],
                "message_count": len(request.conversation_history),
            },
            metadata={"source": self.name},
        )


class RuntimeMetadataProvider(ContextProvider):
    """Provides request and execution metadata without executing the run."""

    name = "runtime_metadata"
    priority = 200

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        return ContextSection(
            provider=self.name,
            priority=self.priority,
            data={
                "run_id": str(request.run_id),
                "user_id": str(request.user_id),
                "request_id": request.request_id,
                "task": request.task,
                "metadata": request.runtime_metadata,
            },
            metadata={"source": self.name},
        )


class UserInformationProvider(ContextProvider):
    """Provides safe, explicitly supplied user attributes."""

    name = "user_information"
    priority = 150

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        user = request.user_information
        return ContextSection(
            provider=self.name,
            priority=self.priority,
            data={
                "user_id": str(user.user_id),
                "email": user.email,
                "full_name": user.full_name,
                "is_active": user.is_active,
            },
            metadata={"source": self.name},
        )


class AgentConfigurationProvider(ContextProvider):
    """Provides the selected agent definition and configuration."""

    name = "agent_configuration"
    priority = 125

    async def build_context(self, request: ContextAssemblyRequest) -> ContextSection:
        configuration = request.agent_configuration
        return ContextSection(
            provider=self.name,
            priority=self.priority,
            data=configuration.model_dump(mode="json"),
            metadata={"source": self.name},
        )


class ContextProviderRegistry:
    """Per-assembler provider registry with deterministic ordering."""

    def __init__(self, providers: Iterable[ContextProvider] = ()) -> None:
        self._providers: dict[str, ContextProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ContextProvider) -> None:
        name = getattr(provider, "name", None)
        priority = getattr(provider, "priority", None)
        if not isinstance(name, str) or not name.strip():
            raise AgentContextConfigurationError("Context provider name must not be blank")
        if not isinstance(priority, int) or priority < 0:
            raise AgentContextConfigurationError(
                f"Context provider {name!r} must define a non-negative priority"
            )
        if name in self._providers:
            raise AgentContextConfigurationError(f"Duplicate context provider: {name}")
        self._providers[name] = provider

    def get(self, name: str) -> ContextProvider | None:
        return self._providers.get(name)

    def providers(self) -> tuple[ContextProvider, ...]:
        return tuple(
            sorted(
                self._providers.values(),
                key=lambda provider: (-provider.priority, provider.name),
            )
        )

    def names(self) -> frozenset[str]:
        return frozenset(self._providers)


class ContextMergeStrategy(Protocol):
    """Merge contract allowing deterministic strategies to be replaced later."""

    def merge(
        self,
        request: ContextAssemblyRequest,
        sections: Sequence[ContextSection],
        metadata: ContextMetadata,
    ) -> ExecutionContext:
        """Merge validated sections into one execution context."""


class PriorityContextMergeStrategy:
    """Merge sections by descending priority, then provider name.

    When sections expose the same data key, the first value wins. Therefore a
    higher priority provider wins conflicts, while equal-priority conflicts are
    resolved by provider name deterministically.
    """

    def merge(
        self,
        request: ContextAssemblyRequest,
        sections: Sequence[ContextSection],
        metadata: ContextMetadata,
    ) -> ExecutionContext:
        ordered_sections = tuple(sorted(sections, key=lambda item: (-item.priority, item.provider)))
        merged: dict[str, Any] = {}
        for section in ordered_sections:
            for key in sorted(section.data):
                merged.setdefault(key, section.data[key])
        return ExecutionContext(
            run_id=request.run_id,
            user_id=request.user_id,
            task=request.task,
            sections=ordered_sections,
            data=merged,
            metadata=metadata,
        )


class ContextBuilder:
    """Fluent builder for a validated, framework-neutral assembly request."""

    def __init__(self, *, limits: ContextLimits | None = None) -> None:
        self._limits = limits or ContextLimits()
        self._run_id: uuid.UUID | None = None
        self._user_id: uuid.UUID | None = None
        self._task: str | None = None
        self._request_id: str | None = None
        self._memory_query: str | None = None
        self._conversation_history: list[ConversationMessage] = []
        self._runtime_metadata: dict[str, Any] = {}
        self._user_information: UserInformation | None = None
        self._agent_configuration: AgentConfiguration | None = None

    def with_run_id(self, run_id: uuid.UUID) -> ContextBuilder:
        self._run_id = run_id
        return self

    def with_user_id(self, user_id: uuid.UUID) -> ContextBuilder:
        self._user_id = user_id
        return self

    def with_task(self, task: str) -> ContextBuilder:
        self._task = task
        return self

    def with_request_id(self, request_id: str | None) -> ContextBuilder:
        self._request_id = request_id
        return self

    def with_memory_query(self, memory_query: str | None) -> ContextBuilder:
        self._memory_query = memory_query
        return self

    def with_conversation_history(
        self,
        messages: Iterable[ConversationMessage],
    ) -> ContextBuilder:
        self._conversation_history = list(messages)
        return self

    def add_message(self, message: ConversationMessage) -> ContextBuilder:
        self._conversation_history.append(message)
        return self

    def with_runtime_metadata(self, metadata: dict[str, Any]) -> ContextBuilder:
        self._runtime_metadata = dict(metadata)
        return self

    def with_user_information(self, user: UserInformation) -> ContextBuilder:
        self._user_information = user
        return self

    def with_agent_configuration(self, configuration: AgentConfiguration) -> ContextBuilder:
        self._agent_configuration = configuration
        return self

    def build(self) -> ContextAssemblyRequest:
        if len(self._conversation_history) > self._limits.max_conversation_messages:
            raise AgentContextLimitError(
                "Conversation history exceeds the configured message limit"
            )
        try:
            return ContextAssemblyRequest(
                run_id=self._run_id,
                user_id=self._user_id,
                task=self._task,
                request_id=self._request_id,
                memory_query=self._memory_query,
                conversation_history=tuple(self._conversation_history),
                runtime_metadata=self._runtime_metadata,
                user_information=self._user_information,
                agent_configuration=self._agent_configuration,
            )
        except ValidationError as exc:
            raise AgentValidationError("Invalid context assembly request") from exc

    build_request = build


class AgentContextAssembler:
    """Collect, validate, prioritize, and merge registered context providers."""

    def __init__(
        self,
        providers: Iterable[ContextProvider] | None = None,
        *,
        required_provider_names: Iterable[str] = DEFAULT_CONTEXT_PROVIDER_NAMES,
        limits: ContextLimits | None = None,
        merge_strategy: ContextMergeStrategy | None = None,
    ) -> None:
        default_providers = (
            ConversationHistoryProvider(),
            RuntimeMetadataProvider(),
            UserInformationProvider(),
            AgentConfigurationProvider(),
        )
        self.registry = ContextProviderRegistry(
            default_providers if providers is None else providers
        )
        self.limits = limits or ContextLimits()
        self.required_provider_names = frozenset(required_provider_names)
        self.merge_strategy = merge_strategy or PriorityContextMergeStrategy()

    def register_provider(self, provider: ContextProvider) -> None:
        self.registry.register(provider)

    async def build_context(self, request: ContextAssemblyRequest) -> ExecutionContext:
        self._validate_request(request)
        missing = self.required_provider_names - self.registry.names()
        if missing:
            names = ", ".join(sorted(missing))
            raise AgentContextConfigurationError(f"Required context providers are missing: {names}")
        if len(self.registry.providers()) > self.limits.max_sections:
            raise AgentContextLimitError("Context provider count exceeds the configured limit")

        sections: list[ContextSection] = []
        for provider in self.registry.providers():
            try:
                section = await provider.build_context(request)
            except AgentContextError:
                raise
            except Exception as exc:
                raise AgentContextProviderError(
                    f"Context provider {provider.name!r} failed to build output"
                ) from exc
            self._validate_provider_output(provider, section)
            sections.append(section)

        metadata = ContextMetadata(
            request_id=request.request_id,
            assembled_at=datetime.now(UTC),
            provider_names=tuple(provider.name for provider in self.registry.providers()),
            section_count=len(sections),
            total_size_bytes=0,
        )
        try:
            context = self.merge_strategy.merge(request, sections, metadata)
        except AgentContextError:
            raise
        except Exception as exc:
            raise AgentContextProviderError("Context merge strategy failed") from exc
        merged_size = _json_size(
            {
                "sections": [section.model_dump(mode="json") for section in context.sections],
                "data": context.data,
            },
            error_type=AgentContextProviderError,
        )
        if merged_size > self.limits.max_total_bytes:
            raise AgentContextLimitError("Assembled context exceeds the configured size limit")
        context = context.model_copy(
            update={
                "metadata": context.metadata.model_copy(update={"total_size_bytes": merged_size})
            }
        )
        self._validate_merged_context(context, request, sections)
        return context

    def _validate_request(self, request: ContextAssemblyRequest) -> None:
        if len(request.task) > self.limits.max_task_length:
            raise AgentContextLimitError("Context task exceeds the configured length limit")
        if len(request.conversation_history) > self.limits.max_conversation_messages:
            raise AgentContextLimitError(
                "Conversation history exceeds the configured message limit"
            )
        self._validate_json_mapping(request.runtime_metadata, "Runtime metadata")
        self._validate_json_mapping(
            request.agent_configuration.configuration,
            "Agent configuration",
        )
        for message in request.conversation_history:
            self._validate_json_mapping(message.metadata, "Conversation message metadata")

    def _validate_provider_output(
        self,
        provider: ContextProvider,
        section: object,
    ) -> None:
        if not isinstance(section, ContextSection):
            raise AgentContextProviderError(
                f"Context provider {provider.name!r} returned an invalid section"
            )
        if section.provider != provider.name:
            raise AgentContextProviderError(
                f"Context provider {provider.name!r} returned section {section.provider!r}"
            )
        if section.priority != provider.priority:
            raise AgentContextProviderError(
                f"Context provider {provider.name!r} returned an invalid priority"
            )
        if len(section.data) > self.limits.max_metadata_keys:
            raise AgentContextLimitError(
                f"Context provider {provider.name!r} returned too many data keys"
            )
        self._validate_json_mapping(section.data, f"Context provider {provider.name!r} data")
        self._validate_json_mapping(
            section.metadata,
            f"Context provider {provider.name!r} metadata",
        )
        section_size = _json_size(
            section.model_dump(mode="json"),
            error_type=AgentContextProviderError,
        )
        if section_size > self.limits.max_section_bytes:
            raise AgentContextLimitError(
                f"Context provider {provider.name!r} exceeded the section size limit"
            )

    def _validate_merged_context(
        self,
        context: object,
        request: ContextAssemblyRequest,
        sections: Sequence[ContextSection],
    ) -> None:
        if not isinstance(context, ExecutionContext):
            raise AgentContextProviderError("Context merge strategy returned an invalid context")
        if context.run_id != request.run_id or context.user_id != request.user_id:
            raise AgentContextProviderError("Context merge strategy returned invalid identity")
        if context.task != request.task:
            raise AgentContextProviderError("Context merge strategy returned an invalid task")
        expected_providers = sorted(section.provider for section in sections)
        actual_providers = sorted(section.provider for section in context.sections)
        if actual_providers != expected_providers:
            raise AgentContextProviderError("Context merge strategy changed context sections")
        if context.metadata.section_count != len(sections):
            raise AgentContextProviderError("Context metadata has an invalid section count")
        if context.metadata.request_id != request.request_id:
            raise AgentContextProviderError("Context metadata has an invalid request id")
        if context.metadata.provider_names != tuple(
            section.provider for section in context.sections
        ):
            raise AgentContextProviderError("Context metadata has invalid provider names")
        self._validate_json_mapping(context.data, "Merged context data")
        merged_size = _json_size(
            {
                "sections": [section.model_dump(mode="json") for section in context.sections],
                "data": context.data,
            },
            error_type=AgentContextProviderError,
        )
        if context.metadata.total_size_bytes != merged_size:
            raise AgentContextProviderError("Context metadata has an invalid size")
        if merged_size > self.limits.max_total_bytes:
            raise AgentContextLimitError("Assembled context exceeds the configured size limit")

    def _validate_json_mapping(self, value: dict[str, Any], label: str) -> None:
        if any(not key.strip() for key in value):
            raise AgentContextProviderError(f"{label} contains a blank key")
        if len(value) > self.limits.max_metadata_keys:
            raise AgentContextLimitError(f"{label} contains too many keys")
        size = _json_size(value, error_type=AgentContextProviderError)
        if size > self.limits.max_metadata_bytes:
            raise AgentContextLimitError(f"{label} exceeds the configured size limit")
