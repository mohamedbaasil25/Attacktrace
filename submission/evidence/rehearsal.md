| Scenario | Target | Detected | Rank of true origin | Detect (s) | Localized (s) | Top-3 |
|---|---|---|---|---|---|---|
| sensor_freeze | LIT101 | Y | 1 | 6.5 | 16.5 | LIT101, PLC2, MV101 |
| sensor_freeze | LIT301 | Y | 1 | 7.5 | 17.5 | LIT301, PLC2, PLC1 |
| sensor_freeze | FIT201 | Y | 1 | 7.0 | 17.0 | FIT201, PLC2, LIT301 |
| sensor_offset | LIT101 | Y | 1 | 1.5 | 11.5 | LIT101, PLC1, MV101 |
| sensor_offset | LIT301 | Y | 1 | 1.5 | 11.5 | LIT301, P301, PLC2 |
| sensor_offset | PIT301 | Y | 1 | 1.5 | 11.5 | PIT301, PLC2, PLC1 |
| sensor_ramp | LIT101 | Y | 1 | 61.5 | 71.5 | LIT101, PLC1, MV101 |
| sensor_ramp | LIT301 | Y | 1 | 45.0 | 55.0 | LIT301, PLC2, FIT201 |
| sensor_ramp | FIT201 | Y | 2 | 9.5 | 19.5 | PLC2, FIT201, LIT301 |
| actuator_force | MV101 | Y | 1 | 1.5 | 11.5 | MV101, PLC1, PLC2 |
| actuator_force | P101 | Y | 1 | 1.5 | 11.5 | P101, FIT201, PIT301 |
| actuator_force | P301 | Y | 1 | 1.5 | 11.5 | P301, PLC2, LIT301 |
| rogue_setpoint | PLC1 | Y | 1 | 1.5 | 11.5 | PLC1, MV101, P101 |
| rogue_setpoint | PLC2 | Y | 2 | 1.5 | 11.5 | P301, PLC2, LIT301 |
| rogue_setpoint | PLC1 | Y | 1 | 1.5 | 11.5 | PLC1, P101, MV101 |
