from typing import Dict, List, Optional, Tuple, Type, TypeVar

from starkware.cairo.lang.compiler.ast.arguments import IdentifierList
from starkware.cairo.lang.compiler.ast.cairo_types import TypeTuple
from starkware.cairo.lang.compiler.ast.code_elements import (
    CodeElementFunction,
    CommentedCodeElement,
)
from starkware.cairo.lang.compiler.error_handling import Location
from starkware.cairo.lang.compiler.preprocessor.identifier_aware_visitor import (
    IdentifierAwareVisitor,
)
from starkware.cairo.lang.compiler.preprocessor.preprocessor_error import PreprocessorError
from starkware.starknet.compiler.data_encoder import ArgumentInfo, EncodingType, encode_data
from starkware.starknet.definitions import constants
from starkware.starknet.public.abi import (
    ACCOUNT_ENTRY_POINT_NAMES,
    EXECUTE_ENTRY_POINT_NAME,
    VALIDATE_DECLARE_ENTRY_POINT_NAME,
    VALIDATE_ENTRY_POINT_NAME,
    AbiEntryType,
    AbiType,
)

TAttr = TypeVar("TAttr")

# Common verifications.


def verify_no_implicit_arguments(elm: CodeElementFunction, name_in_error_message: str):
    """
    Verifies that the given element has no implicit arguments and raises an exception
    otherwise.
    """
    if elm.implicit_arguments is not None and len(elm.implicit_arguments.identifiers) != 0:
        raise PreprocessorError(
            message=f"{name_in_error_message} must have no implicit arguments.",
            location=elm.implicit_arguments.location,
        )


def verify_decorators(
    elm: CodeElementFunction, allowed_decorators: List[str], name_in_error_message: str
):
    """
    Verifies that the decorators of the given element are as expected and raises an exception
    otherwise.
    """
    for decorator in elm.decorators:
        if decorator.name not in allowed_decorators:
            raise PreprocessorError(
                f"Unexpected decorator for {name_in_error_message}.",
                location=decorator.location,
            )


def verify_starknet_lang(
    file_lang: Optional[str], location: Optional[Location], name_in_error_message: str
):
    """
    Verifies that file_lang equals STARKNET_LANG_DIRECTIVE and raises an exception otherwise.
    """
    if file_lang != constants.STARKNET_LANG_DIRECTIVE:
        raise PreprocessorError(
            f"{name_in_error_message} can only be used in source files that contain the "
            '"%lang starknet" directive.',
            location=location,
        )


def verify_no_return_values(elm: CodeElementFunction, name_in_error_message: str):
    """
    Verifies that the given element has no return values and raises an exception
    otherwise.
    """
    returns = elm.returns
    if returns is None:
        return

    if not isinstance(returns, TypeTuple) or len(returns.members) > 0:
        raise PreprocessorError(
            message=f"{name_in_error_message} must have no return values.",
            location=returns.location,
        )


def verify_account_contract(contract_abi: AbiType, is_account_contract: bool):
    """
    For account contracts (is_account_contract=True), verifies that the given ABI contains
    all expected builtin entry points in their correct format.
    For non-account contracts, verifies that it contains none of them.
    """
    account_entry_points: Dict[str, AbiEntryType] = {}

    # Collect account contract special entry points.
    for entry_point in contract_abi:
        if entry_point["type"] == "function" and entry_point["name"] in ACCOUNT_ENTRY_POINT_NAMES:
            account_entry_points[entry_point["name"]] = entry_point

    account_entry_point_names = set(account_entry_points.keys())

    if is_account_contract:
        # Handle account contract.
        if account_entry_point_names != ACCOUNT_ENTRY_POINT_NAMES:
            raise PreprocessorError(
                message=(
                    "Account contracts must have external functions named "
                    f"{ACCOUNT_ENTRY_POINT_NAMES}, found: {list(account_entry_point_names)}."
                )
            )

        validate_entry_point = account_entry_points[VALIDATE_ENTRY_POINT_NAME]
        execute_entry_point = account_entry_points[EXECUTE_ENTRY_POINT_NAME]
        validate_declare_entry_point = account_entry_points[VALIDATE_DECLARE_ENTRY_POINT_NAME]
        if execute_entry_point["inputs"] != validate_entry_point["inputs"]:
            raise PreprocessorError(
                message=(
                    "Account contracts must have the exact same calldata for "
                    f"'{VALIDATE_ENTRY_POINT_NAME}' and '{EXECUTE_ENTRY_POINT_NAME}' functions."
                )
            )

        if validate_declare_entry_point["inputs"] != [{"name": "class_hash", "type": "felt"}]:
            raise PreprocessorError(
                message=(
                    f"'{VALIDATE_DECLARE_ENTRY_POINT_NAME}' function must have one argument "
                    "`class_hash: felt`."
                )
            )
    else:
        # Handle non-account contract.
        if len(account_entry_point_names) > 0:
            # One of the entry points exists in a non-account contract.
            raise PreprocessorError(
                message=(
                    f"Only account contracts may have functions named {account_entry_point_names}. "
                    "Use the --account_contract flag to compile an account contract."
                )
            )


# Common utils.


def has_decorator(elm: CodeElementFunction, decorator_name: str) -> Tuple[bool, Optional[Location]]:
    """
    Returns whether the given function has the given decorator.
    If it does, the location of the decorator is returned.
    """
    for decorator in elm.decorators:
        if decorator.name == decorator_name:
            return True, decorator.location
    return False, None


def get_function_attr(
    elm: CodeElementFunction, attr_name: str, attr_type: Type[TAttr]
) -> Optional[TAttr]:
    """
    Returns the given attribute of the given function, if exists; returns None otherwise.
    """
    attr = elm.additional_attributes.get(attr_name)
    assert attr is None or isinstance(
        attr, attr_type
    ), f"Unexpected attribute under {attr_name} key: {type(attr).__name__}."

    return attr


def non_optional_location(location: Optional[Location]) -> Location:
    assert location is not None
    return location


def encode_calldata_arguments(
    arguments: IdentifierList, visitor: IdentifierAwareVisitor
) -> List[CommentedCodeElement]:
    """
    Generates code that flattens the given calldata-encoded arguments to a sequence of felts
    under __calldata_ptr pointer - i.e., it should be defined before calling this function.
    """
    argument_infos = [
        ArgumentInfo(
            name=typed_identifier.identifier.name,
            cairo_type=visitor.resolve_type(typed_identifier.get_type()),
            location=non_optional_location(typed_identifier.identifier.location),
        )
        for typed_identifier in arguments.identifiers
    ]

    return encode_data(
        arguments=argument_infos,
        encoding_type=EncodingType.CALLDATA,
        has_range_check_builtin=True,
        identifiers=visitor.identifiers,
    )
