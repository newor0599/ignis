from __future__ import annotations
import datetime
from gi.repository import GObject, GLib  # type: ignore
from ignis.app import IgnisApp
from ignis.services.options import OptionsService
from ignis.services.audio import AudioService
from ignis.exceptions import GstPluginNotFoundError
from ignis.base_service import BaseService
from .session import SessionManager
from .util import gst_inspect
from ._imports import Gst
from .constants import PIPELINE_TEMPLATE, MAIN_AUDIO_PIPELINE, AUDIO_DEVICE_PIPELINE
from .options import (
    RECORDING_BITRATE_OPTION,
    RECORDING_DEFAULT_FILE_LOCATION_OPTION,
    RECORDING_DEFAULT_FILENAME_OPTION,
)

app = IgnisApp.get_default()


class RecorderService(BaseService):
    """
    A screen recorder.
    Uses XDG Desktop portal and PipeWire.
    Allow record screen with microphone audio and internal system audio.

    **Dependencies**:
        - **GStreamer**
        - **PipeWire**
        - **gst-plugin-pipewire**
        - **gst-plugins-good**
        - **gst-plugins-ugly**
        - **pipewire-pulse**: for audio recording.

    Signals:
        - **"recording_started"** (): Emitted when recording starts.
        - **"recording_stopped"** (): Emitted when recording stops.

    Properties:
        - **active** (``bool``, read-write): Whether recording is currently active.
        - **is_paused** (``bool``, read-write): Whether recording is currently paused.
        - **bitrate** (``int``, read-write, default: 8000): The bitrate of the recording.
        - **default_file_location** (``str``, read-write, default: ``"$HOME/Videos"``): Default location for saving recordings.
        - **default_filename** (``str``, read-write, default: ``"%Y-%m-%d_%H-%M-%S.mp4"``): Default filename for recordings. Supports time formating.

    Raises:
        GstNotFoundError: If GStreamer is not found.
        GstPluginNotFoundError: If GStreamer plugin is not found.

    **Example usage:**

    .. code-block:: python

        from ignis.services.recorder import RecorderService
        from ignis.utils import Utils

        recorder = RecorderService.get_default()

        recorder.start_recording(record_internal_audio=True)

        # record for 30 seconds and then stop
        Utils.Timeout(ms=30 * 1000, target=recorder.stop_recording)
    """

    __gsignals__ = {
        "recording_started": (GObject.SignalFlags.RUN_FIRST, GObject.TYPE_NONE, ()),
        "recording_stopped": (GObject.SignalFlags.RUN_FIRST, GObject.TYPE_NONE, ()),
    }

    def __init__(self):
        super().__init__()
        self.__check_deps()
        Gst.init(None)

        self.__manager = SessionManager()

        self._active: bool = False
        self._is_paused: bool = False
        self.__pipeline: Gst.Element | None = None

        self._N_THREADS: str = str(min(max(1, GLib.get_num_processors()), 64))

        self._options = OptionsService.get_default()
        self._audio = AudioService.get_default()

        self._options.create_option(
            name=RECORDING_BITRATE_OPTION, default=8000, exists_ok=True
        )
        self._options.create_option(
            name=RECORDING_DEFAULT_FILE_LOCATION_OPTION,
            default=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS),
            exists_ok=True,
        )
        self._options.create_option(
            name=RECORDING_DEFAULT_FILENAME_OPTION,
            default="%Y-%m-%d_%H-%M-%S.mp4",
            exists_ok=True,
        )

        app.connect("quit", lambda x: self.stop_recording())

    def __check_deps(self) -> None:
        if not gst_inspect("pipewiresrc"):
            raise GstPluginNotFoundError("PipeWire", "gst-plugin-pipewire")

        if not gst_inspect("x264enc"):
            raise GstPluginNotFoundError("H.264 encoder", "gst-plugins-ugly")

        if not gst_inspect("mp4mux"):
            raise GstPluginNotFoundError("MP4 muxer", "gst-plugins-good")

    @GObject.Property
    def active(self) -> bool:
        return self._active

    @GObject.Property
    def is_paused(self) -> bool:
        return self._is_paused

    @GObject.Property
    def bitrate(self) -> int:
        return self._options.get_option(RECORDING_BITRATE_OPTION)

    @bitrate.setter
    def bitrate(self, value: int) -> None:
        self._options.set_option(RECORDING_BITRATE_OPTION, value)

    @GObject.Property
    def default_file_location(self) -> str:
        return self._options.get_option(RECORDING_DEFAULT_FILE_LOCATION_OPTION)

    @default_file_location.setter
    def default_file_location(self, value: str) -> None:
        self._options.set_option(RECORDING_DEFAULT_FILE_LOCATION_OPTION, value)

    @GObject.Property
    def default_filename(self) -> str:
        return self._options.get_option(RECORDING_DEFAULT_FILENAME_OPTION)

    @default_filename.setter
    def default_filename(self, value: str) -> None:
        self._options.set_option(RECORDING_DEFAULT_FILENAME_OPTION, value)

    def start_recording(
        self,
        path: str | None = None,
        record_microphone: bool = False,
        record_internal_audio: bool = False,
        audio_devices: list[str] | None = None,
    ) -> None:
        """
        Start recording.

        Args:
            path (``str``, optional): Recording path. It will override ``default_file_location`` and ``default_filename`` properties.
            record_microphone (``bool``, optional): Whether record audio from microphone.
            record_internal_audio (``bool``, optional): Whether record internal audio.
            audio_devices (``list[str]``, optional): A list of audio devices names from which audio should be recorded.
        """

        if path is None:
            path = f"{self.default_file_location}/{datetime.datetime.now().strftime(self.default_filename)}"

        pipeline_description = (
            PIPELINE_TEMPLATE.replace("{n_threads}", self._N_THREADS)
            .replace("{path}", path)
            .replace("{bitrate}", str(self.bitrate))
        )

        audio_pipeline = ""

        if record_microphone:
            audio_pipeline = self.__combine_audio_pipeline(
                audio_pipeline, self._audio.microphone.name
            )

        if record_internal_audio:
            audio_pipeline = self.__combine_audio_pipeline(
                audio_pipeline, self._audio.speaker.name + ".monitor"
            )

        if audio_devices:
            for device in audio_devices:
                audio_pipeline = self.__combine_audio_pipeline(audio_pipeline, device)

        pipeline_description += audio_pipeline

        self.__manager.start_session(self.__play_pipewire_stream, pipeline_description)

    def __combine_audio_pipeline(self, audio_pipeline: str, device: str) -> str:
        if audio_pipeline != "":
            template = AUDIO_DEVICE_PIPELINE
        else:
            template = MAIN_AUDIO_PIPELINE

        audio_pipeline += template.replace("{device}", device)
        return audio_pipeline

    def stop_recording(self) -> None:
        """
        Stop recording.
        """
        if self.__pipeline:
            self.__pipeline.send_event(Gst.Event.new_eos())
            self.__pipeline.set_state(Gst.State.NULL)
            self.__pipeline = None
            self._pipeline_description = ""
            self._active = False
            self._is_paused = False
            self.notify("active")
            self.notify("is-paused")
            self.emit("recording_stopped")

    def pause_recording(self) -> None:
        """
        Pause recording. This has an effect only if the recording is active and not already paused.
        """
        if self.__pipeline:
            self._is_paused = True
            self.__pipeline.set_state(Gst.State.PAUSED)
            self.notify("is-paused")

    def continue_recording(self) -> None:
        """
        Continue recording. This has an effect only if the recording is active and paused.
        """
        if self.__pipeline:
            self._is_paused = False
            self.__pipeline.set_state(Gst.State.PLAYING)
            self.notify("is-paused")

    def __play_pipewire_stream(self, node_id: int, pipeline_description: str) -> None:
        pipeline_description = pipeline_description.replace("{node_id}", str(node_id))

        self.__pipeline = Gst.parse_launch(pipeline_description)
        self.__pipeline.set_state(Gst.State.PLAYING)
        bus = self.__pipeline.get_bus()
        if not bus:
            return

        bus.connect("message", self.__on_gst_message)

        self._active = True
        self._is_paused = False

        self.notify("active")
        self.notify("is-paused")
        self.emit("recording_started")

    def __on_gst_message(self, bus, message):
        if message.type == Gst.MessageType.EOS or message.type == Gst.MessageType.ERROR:
            self.stop_recording()