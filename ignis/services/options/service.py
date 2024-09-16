import sys
import json
from ignis.gobject import Binding
from typing import Any, Callable
from ignis.exceptions import OptionExistsError, OptionNotFoundError
from ignis.base_service import BaseService
from .option import Option
from .constants import OPTIONS_FILE


class OptionsService(BaseService):
    """
    Service to manage options.
    This service stores options and their values in the ``~/.cache/ignis/options.json`` file.

    .. warning::
        You should not manually edit the ``~/.cache/ignis/options.json`` file.
        Use this service instead.


    **Example usage:**

    .. code-block:: python

        from ignis.services.options import OptionsService

        options = OptionsService.get_default()

        SOME_OPTION = "some_option"

        options.create_option(name=SOME_OPTION, default="hi", exists_ok=True)
        options.set_option(SOME_OPTION, "bye")

        print(options.get_option(SOME_OPTION))

    """

    def __init__(self):
        super().__init__()
        self.__data: dict[str, Option] = {}
        self.__load_data()

    def __load_data(self) -> None:
        if "sphinx" in sys.modules:
            return

        try:
            with open(OPTIONS_FILE) as file:
                data = json.load(file)

                for i in data.keys():
                    self.__data[i] = Option(name=i, value=data[i])

        except FileNotFoundError:
            with open(OPTIONS_FILE, "w") as file:
                json.dump({}, file)

    def __sync(self) -> None:
        json_dict = {}

        for key, option in self.__data.items():
            json_dict[key] = option.value

        with open(OPTIONS_FILE, "w") as file:
            json.dump(json_dict, file, indent=2)

    def create_option(self, name: str, default: Any, exists_ok: bool = False) -> None:
        """
        Create an option.

        Args:
            name (``str``): The name of the option.
            default (``Any``): The default value for the option.
            exists_ok (``bool``, optional): If ``True``, do not raise ``OptionExistsError`` if the option already exists. Default: ``False``.

        Raises:
            OptionExistsError: If the option already exists and ``exists_ok`` is set to ``False``.
        """

        option = self.__data.get(name, None)
        if not option:
            self.__data[name] = Option(name=name, value=default)
            self.__sync()
        else:
            if not exists_ok:
                raise OptionExistsError(name)

    def remove_option(self, name: str) -> None:
        """
        Remove an option.

        Args:
            name (``str``): The name of the option to be removed.

        Raises:
            OptionNotFoundError: If the option does not exist.
        """
        option = self.__data.get(name, None)
        if option:
            self._data.pop(name)
        else:
            raise OptionNotFoundError(name)

    def get_option(self, name: str) -> Any:
        """
        Retrieve the value of an option by its name.

        Args:
            name (``str``): The name of the option.

        Returns:
            The value of the option.

        Raises:
            OptionNotFoundError: If the option does not exist.
        """
        option = self.__data.get(name, None)

        if option:
            return option.value
        else:
            raise OptionNotFoundError(name)

    def set_option(self, name: str, value: Any) -> None:
        """
        Set the value of an option by its name.

        Args:
            name (``str``): The name of the option.
            value (``Any``): The value to set for the option.
        Raises:
            OptionNotFoundError: If the option does not exist.
        """
        option = self.__data.get(name, None)
        if option:
            option.value = value
        else:
            raise OptionNotFoundError(name)
        self.__sync()

    def bind_option(self, name: str, transform: Callable | None = None) -> Binding:
        """
        Like ``bind()``, but for option.

        Args:
            name (``str``): The name of the option to bind.
            transform (``Callable``, optional): A transform function.

        Returns:
            ``Binding``.

        Raises:
            OptionNotFoundError: If the option does not exist.
        """
        option = self.__data.get(name, None)
        if not option:
            raise OptionNotFoundError(name)

        return Binding(option, "value", transform)

    def connect_option(self, name: str, callback: Callable) -> None:
        """
        Associate a callback function with changes to an option value.
        When the option value changes, the callback function will be invoked with the new value.

        Args:
            name (``str``): The name of the option.
            callback (``Callable``): A function to call when the option value changes. The new value of the option will be passed to this function.

        Raises:
            OptionNotFoundError: If the option does not exist.
        """
        option = self.__data.get(name, None)
        if not option:
            raise OptionNotFoundError(name)

        option.connect("notify::value", lambda x, y: callback(option.value))