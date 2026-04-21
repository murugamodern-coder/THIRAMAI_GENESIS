from __future__ import annotations

from pydantic import BaseModel, Field


class CommandAST(BaseModel):
    binary: str
    sub_command: str = ""
    args: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    has_pipes: bool = False
    has_redirection: bool = False
    has_chaining: bool = False


class CommandParser:
    _PIPE_MARKERS = ("|", "||")
    _REDIRECTION_MARKERS = (">", ">>", "<", "2>", "2>>")
    _CHAIN_MARKERS = (";", "&&", "||")
    _METACHAR_FRAGMENTS = (";", "&&", "||", "|", ">", "<")

    def parse(self, command_parts: list[str]) -> CommandAST:
        if not command_parts:
            raise ValueError("Command parts are empty.")

        cleaned = [str(token).strip() for token in command_parts if str(token).strip()]
        if not cleaned:
            raise ValueError("Command parts are empty after normalization.")

        binary = cleaned[0].lower()
        has_pipes = self._contains_pipe(cleaned)
        has_redirection = self._contains_redirection(cleaned)
        has_chaining = self._contains_chaining(cleaned)

        flags: list[str] = []
        positional: list[str] = []
        for token in cleaned[1:]:
            if token.startswith("-"):
                flags.append(token.lower())
            else:
                positional.append(token.lower())

        sub_command = positional[0] if positional else ""
        args = positional[1:] if len(positional) > 1 else []

        return CommandAST(
            binary=binary,
            sub_command=sub_command,
            args=args,
            flags=flags,
            has_pipes=has_pipes,
            has_redirection=has_redirection,
            has_chaining=has_chaining,
        )

    def _contains_pipe(self, tokens: list[str]) -> bool:
        for token in tokens:
            if token in self._PIPE_MARKERS:
                return True
            if "|" in token:
                return True
        return False

    def _contains_redirection(self, tokens: list[str]) -> bool:
        for token in tokens:
            if token in self._REDIRECTION_MARKERS:
                return True
            if ">" in token or "<" in token:
                return True
        return False

    def _contains_chaining(self, tokens: list[str]) -> bool:
        for token in tokens:
            if token in self._CHAIN_MARKERS:
                return True
            for marker in self._METACHAR_FRAGMENTS:
                if marker in token and token not in self._REDIRECTION_MARKERS and token not in self._PIPE_MARKERS:
                    return True
        return False
