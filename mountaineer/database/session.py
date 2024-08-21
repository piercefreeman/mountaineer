from typing import (
    Any,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Union,
    overload,
)

from sqlalchemy import util
from sqlalchemy.engine.result import ScalarResult, TupleResult
from sqlalchemy.sql.elements import TextClause
from sqlmodel.ext.asyncio.session import AsyncSession as AsyncSessionBase, _TSelectParam
from sqlmodel.sql.base import Executable
from sqlmodel.sql.expression import Select, SelectOfScalar


class AsyncSession(AsyncSessionBase):
    """
    Provide additional support for common Mountaineer types.

    """

    @overload
    async def exec(
        self,
        statement: Select[_TSelectParam],
        *,
        params: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = util.EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> TupleResult[_TSelectParam]:
        ...

    @overload
    async def exec(
        self,
        statement: SelectOfScalar[_TSelectParam],
        *,
        params: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = util.EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> ScalarResult[_TSelectParam]:
        ...

    # @pierce - Relevant conversation https://github.com/fastapi/sqlmodel/issues/909
    @overload
    async def exec(
        self,
        statement: TextClause,
        *,
        params: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = util.EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> Any:
        ...

    async def exec(
        self,
        statement: Union[
            Select[_TSelectParam],
            SelectOfScalar[_TSelectParam],
            Executable[_TSelectParam],
            TextClause,
        ],
        *,
        params: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = util.EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> Union[TupleResult[_TSelectParam], ScalarResult[_TSelectParam], Any]:
        return await super().exec(  # type: ignore
            statement=statement,  # type: ignore
            params=params,
            execution_options=execution_options,
            bind_arguments=bind_arguments,
            _parent_execute_state=_parent_execute_state,
            _add_event=_add_event,
        )
