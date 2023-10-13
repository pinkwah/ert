from typing import Generic, Optional, Type, TypeVar
from qtpy.QtCore import Signal
from qtpy.QtWidgets import QDialog, QWidget, QAction


T = TypeVar("T", bound=QDialog)


class ToolButton(QWidget, Generic[T]):
    created = Signal(QDialog)

    def __init__(
        self,
        dialog_type: Type[T],
        icon: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._dialog_type = dialog_type
        self._dialog: Optional[T] = None

        action = QAction(
            icon,
        )

    def trigger(self) -> T:
        if (dialog := self._dialog) is None:
            dialog = self._dialog = self._dialog_type()
            self.created.emit(dialog)
        dialog.open()
        return dialog
