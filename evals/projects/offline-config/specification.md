# Offline Configuration Validator

## Functional requirements

- `FR-CFG-001`: The command must validate one UTF-8 JSON configuration file.
- `FR-CFG-002`: The command must report every unknown key without modifying the input.
- `FR-CFG-003`: The command must return a non-zero exit status for invalid configuration.

## Non-functional requirements

- `NFR-CFG-001`: Validation must complete within two seconds for files up to one megabyte.

## Constraints

- `C-CFG-001`: The core must operate without network access.
- `C-CFG-002`: The implementation must use no third-party runtime dependency.

## Non-goals

- `NG-CFG-001`: The project must not edit configuration files.
