| Scenario | Target | Detected | Rank of true origin | Detect (s) | Localized (s) | Top-3 |
|---|---|---|---|---|---|---|
| sensor_freeze | LIT101 | Y | 1 | 7.5 | 17.5 | LIT101, LIT301, PLC2 |
| sensor_freeze | LIT301 | Y | 1 | 6.5 | 16.5 | LIT301, PLC2, MV101 |
| sensor_freeze | FIT201 | Y | 1 | 7.0 | 17.0 | FIT201, MV101, PLC1 |
| sensor_offset | LIT101 | Y | 1 | 2.0 | 12.0 | LIT101, PLC1, MV101 |
| sensor_offset | LIT301 | Y | 1 | 2.0 | 12.0 | LIT301, PLC2, P301 |
| sensor_offset | PIT301 | Y | 1 | 2.0 | 12.0 | PIT301, PLC1, LIT301 |
| sensor_ramp | LIT101 | Y | >3 | 61.5 | 71.5 | PLC1, MV101, P101 |
| sensor_ramp | LIT301 | Y | 2 | 48.0 | 58.0 | PLC2, LIT301, FIT201 |
| sensor_ramp | FIT201 | Y | 1 | 9.0 | 19.0 | FIT201, LIT301, MV101 |
| actuator_force | MV101 | Y | 2 | 2.0 | 12.0 | PLC1, MV101, LIT101 |
| actuator_force | P101 | Y | 2 | 2.0 | 12.0 | LIT101, P101, FIT201 |
| actuator_force | P301 | Y | 1 | 2.0 | 12.0 | P301, LIT301, PLC2 |
| rogue_setpoint | PLC1 | Y | 2 | 2.0 | 12.0 | LIT101, PLC1, MV101 |
| rogue_setpoint | PLC2 | Y | 1 | 2.0 | 12.0 | PLC2, P301, LIT301 |
| rogue_setpoint | PLC1 | Y | 2 | 2.0 | 12.0 | LIT101, PLC1, P101 |
