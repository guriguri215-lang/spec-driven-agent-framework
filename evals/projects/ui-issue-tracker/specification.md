# Offline Issue Tracker

## Functional requirements

- `FR-UIT-001`: A user must create an issue with a title and status.
- `FR-UIT-002`: A user must move an issue between open and closed states.
- `FR-UIT-003`: The application must persist issues in local project storage.
- `FR-UIT-004`: The interface must present loading, empty, error, permission-denied, and offline states.

## Non-functional requirements

- `NFR-UIT-001`: Every primary flow must support keyboard operation and a visible focus order.
- `NFR-UIT-002`: Text and controls must meet the documented contrast threshold.

## Constraints

- `C-UIT-001`: Core issue management must operate without network access.

## Non-goals

- `NG-UIT-001`: The project must not add account authentication or cloud synchronization.
