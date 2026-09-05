"""External-system adapters into the PM-Software native project model."""

from .msproject_xml import ImportedDecisionArea, import_mspdi_decision_area

__all__ = ["ImportedDecisionArea", "import_mspdi_decision_area"]
