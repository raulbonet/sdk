"""Abstract base class for loading a single singer stream to its target."""

import abc
import datetime

from logging import Logger
from types import MappingProxyType
from typing import Dict, Optional, List, Any, Mapping, Union

from singer_sdk.helpers._compat import final

# from jsonschema import Draft4Validator, FormatChecker
# from singer_sdk.helpers._flattening import RecordFlattener

from singer_sdk.helpers._typing import (
    get_datelike_property_type,
    handle_invalid_timestamp_in_record,
    DatetimeErrorTreatmentEnum,
)
from singer_sdk.plugin_base import PluginBase

from dateutil import parser


class Sink(metaclass=abc.ABCMeta):
    """Abstract base class for target streams."""

    # max timestamp/datetime supported, used to reset invalid dates

    logger: Logger
    schema: Dict
    stream_name: str

    # Tally counters
    _num_records_since_flush: int = 0
    _total_records_read: int = 0
    _total_records_written: int = 0
    _dupe_records_merged: int = 0

    MAX_SIZE_DEFAULT = 10000

    # TODO: Re-implement schema validation
    # _validator: Draft4Validator
    # _flattener: Optional[RecordFlattener]
    # _MAX_FLATTEN_DEPTH = 0

    def __init__(
        self,
        target: PluginBase,
        stream_name: str,
        schema: Dict,
        key_properties: Optional[List[str]],
    ) -> None:
        """Initialize target stream."""
        self.logger = target.logger
        self._config = dict(target.config)
        self.schema = schema
        self.stream_name = stream_name
        self.logger.info("Initializing target sink for stream '{stream_name}'...")
        self.records_to_flush: List[Union[dict, Any]] = []

        # TODO: Re-implement schema validation
        # self._flattener = RecordFlattener(max_level=self._MAX_FLATTEN_DEPTH)
        # self._validator = Draft4Validator(schema, format_checker=FormatChecker())

    # Tally methods

    @property
    def max_size(self) -> int:
        """Return the max number of unflushed records before is_full=True."""
        return self.MAX_SIZE_DEFAULT

    @property
    def current_size(self) -> int:
        """Return the number of unflushed records."""
        return len(self.records_to_flush)

    @property
    def is_full(self) -> bool:
        """Return True if the sink needs to be flushed."""
        return self.current_size >= self.max_size

    @final
    def tally_record_read(self, count: int = 1):
        """Increment the records read tally.

        This method is called automatically by the SDK.
        """
        self._total_records_read += count

    @final
    def tally_record_written(self, count: int = 1):
        """Increment the records written tally.

        This method should be called directly by the Target implementation.
        """
        self._total_records_written += count

    @final
    def tally_duplicate_merged(self, count: int = 1):
        """Increment the records merged tally.

        This method should be called directly by the Target implementation.
        """
        self._dupe_records_merged += count

    # Properties

    @property
    def config(self) -> Mapping[str, Any]:
        """Return a frozen (read-only) config dictionary map."""
        return MappingProxyType(self._config)

    @property
    def include_sdc_metadata_properties(self) -> bool:
        """Return True if metadata columns should be added."""
        return True

    @property
    def primary_keys_required(self) -> bool:
        """Return True if primary keys are required."""
        return self.config.get("primary_keys_required", False)

    @property
    def datetime_error_treatment(self) -> DatetimeErrorTreatmentEnum:
        """Return a treatment to use for datetime parse errors: ERROR. MAX, or NULL."""
        return DatetimeErrorTreatmentEnum.ERROR

    # Record processing

    @staticmethod
    def _add_metadata_values_to_record(record: dict, message: dict) -> None:
        """Populate metadata _sdc columns from incoming record message."""
        record["_sdc_extracted_at"] = message.get("time_extracted")
        record["_sdc_batched_at"] = datetime.datetime.now().isoformat()
        record["_sdc_deleted_at"] = record.get("_sdc_deleted_at")

    # Record validation

    def _validate_record(self, record: Dict) -> Dict:
        """Validate or repair the record."""
        self._validate_timestamps_in_record(
            record=record, schema=self.schema, treatment=self.datetime_error_treatment
        )
        return record

    def _validate_timestamps_in_record(
        self, record: Dict, schema: Dict, treatment: DatetimeErrorTreatmentEnum
    ) -> None:
        """Confirm or repair date or timestamp values in record.

        Goes through every field that is of type date/datetime/time and if its value is
        out of range, send it to self._handle_invalid_timestamp_in_record() and use the
        return value as replacement.
        """
        for key in record.keys():
            datelike_type = get_datelike_property_type(key, schema["properties"][key])
            if datelike_type:
                try:
                    date_val = record[key]
                    date_val = parser.parse(date_val)
                except Exception as ex:
                    date_val = handle_invalid_timestamp_in_record(
                        record,
                        [key],
                        date_val,
                        datelike_type,
                        ex,
                        treatment,
                        self.logger,
                    )
                record[key] = date_val

    # SDK developer overrides:

    def preprocess_record(self, record: Dict) -> dict:
        """Process incoming record and return the result."""
        return record

    async def load_record(self, record: dict) -> None:
        """Flush all queued records to the target.

        This method can write permanently or write to a buffer/staging area.

        By default, append record to `records_to_flush`, to be written during `flush()`.

        Call `tally_record_written()` here or in `flush()` to confirm total records
        permanently written. If duplicates are merged, these can be tracked via
        `tally_duplicates_merged()`
        """
        self.records_to_flush.append(record)

    def flush(self) -> None:
        """Flush all records in self.records_to_flush.

        Call `tally_record_written()` here or in `load_record()` to confirm total
        records permanently written.

        If duplicates are merged, these can optionally be tracked via
        `tally_duplicates_merged()`.
        """
        if self.records_to_flush:
            raise NotImplementedError(
                "Unflushed records were detected and no handling exists for flush()."
            )
