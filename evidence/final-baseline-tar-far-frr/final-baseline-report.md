# Final baseline comparison — TAR / FAR / FRR

> This report states observed TAR, FAR and FRR at predeclared FAR targets, swept over each algorithm's own raw-score scale on identical planned pairs. It performs no calibration, selects no operational threshold, normalizes no score, compares no raw score across algorithms, and interpolates nothing.

- Comparison: `final_baseline_tar_far_frr_v1`
- Roster: `final_baseline_roster_v1`
- Report profile: `final_baseline_reporting_v1`
- Stage 21A finalization: `4b179dad7053ae1ada3cb2dd1fede4e37531c20b2b07b67ebc4a90173c860c86`
- Stage 21B finalization: `2e18d406f08b1adb35e7af57e7a30c94569ed25764f78aa0b9dd701bc2a436d7`
- Genuine population: `plain_roll_mated` (legacy plain↔roll mated, 500 per release)
- Impostor population: `plain_roll_cross_subject_non_mated` (exhaustive cross-subject, 24,500 per release)

## How to read this report

- The reporting point is the highest observed TAR at or below each predeclared FAR target; equal scores move together and nothing is interpolated.
- A genuine algorithm failure is not accepted (it stays in the TAR/FRR denominator); an impostor failure is not a false accept (it stays in the FAR denominator).
- A score cut is an observed reporting boundary on one algorithm's own scale. It is not an operating threshold, it is never reused by execution, and cuts are never compared across algorithms.
- Ranking rule: highest TAR at or below the requested FAR, ties resolved by frozen roster order; primary view, all planned attempts.

## Primary view — all planned attempts

### FAR target ≤ 1/1000 (primary)

#### SD300A

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.2000% (486/500) | 2.8000% (14/500) | 0.0367% (9/24500) | ≥ 49.0 | 491/500 | 24059/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 88.4000% (442/500) | 11.6000% (58/500) | 0.0898% (22/24500) | ≥ 0.12013983821960014 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 82.0000% (410/500) | 18.0000% (90/500) | 0.0735% (18/24500) | ≥ 18.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 75.8000% (379/500) | 24.2000% (121/500) | 0.0898% (22/24500) | ≥ 24.42412632657382 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.6000% (13/500) | 97.4000% (487/500) | 0.0816% (20/24500) | ≥ 2.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 0.2000% (1/500) | 99.8000% (499/500) | 0.0531% (13/24500) | ≥ 1.9780957102775574 | 500/500 | 24500/24500 |

#### SD300B

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.4000% (487/500) | 2.6000% (13/500) | 0.0694% (17/24500) | ≥ 46.0 | 490/500 | 24010/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 87.6000% (438/500) | 12.4000% (62/500) | 0.0816% (20/24500) | ≥ 0.12057181836005533 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 83.2000% (416/500) | 16.8000% (84/500) | 0.0694% (17/24500) | ≥ 18.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 74.4000% (372/500) | 25.6000% (128/500) | 0.0612% (15/24500) | ≥ 24.48687767576256 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.8000% (9/500) | 98.2000% (491/500) | 0.0980% (24/24500) | ≥ 2.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 0.2000% (1/500) | 99.8000% (499/500) | 0.0327% (8/24500) | ≥ 1.9793428182601929 | 500/500 | 24500/24500 |

#### SD300C

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.6000% (488/500) | 2.4000% (12/500) | 0.0531% (13/24500) | ≥ 48.0 | 492/500 | 24108/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 89.0000% (445/500) | 11.0000% (55/500) | 0.0816% (20/24500) | ≥ 0.11940436835824061 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 83.2000% (416/500) | 16.8000% (84/500) | 0.0653% (16/24500) | ≥ 18.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 72.8000% (364/500) | 27.2000% (136/500) | 0.0694% (17/24500) | ≥ 24.11070116891654 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.4000% (7/500) | 98.6000% (493/500) | 0.0000% (0/24500) | ≥ 3.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 0.2000% (1/500) | 99.8000% (499/500) | 0.0204% (5/24500) | ≥ 1.9797134399414062 | 500/500 | 24500/24500 |

#### pooled

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.4000% (1461/1500) | 2.6000% (39/1500) | 0.0707% (52/73500) | ≥ 46.0 | 1473/1500 | 72177/73500 |
| NBIS MINDTCT + MCC SDK v2.0 | 88.3333% (1325/1500) | 11.6667% (175/1500) | 0.0925% (68/73500) | ≥ 0.11940436835824061 | 1500/1500 | 73500/73500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 82.8000% (1242/1500) | 17.2000% (258/1500) | 0.0694% (51/73500) | ≥ 18.0 | 1500/1500 | 73500/73500 |
| SourceAFIS Java 3.18.1 | 74.5333% (1118/1500) | 25.4667% (382/1500) | 0.0993% (73/73500) | ≥ 23.379102652238423 | 1500/1500 | 73500/73500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.0000% (30/1500) | 98.0000% (1470/1500) | 0.0980% (72/73500) | ≥ 2.0 | 1500/1500 | 73500/73500 |
| FLX DeepPrint TexMinu 512 without localization | 0.2000% (3/1500) | 99.8000% (1497/1500) | 0.0408% (30/73500) | ≥ 1.9780957102775574 | 1500/1500 | 73500/73500 |

### FAR target ≤ 1/100

#### SD300A

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.6000% (488/500) | 2.4000% (12/500) | 0.1429% (35/24500) | ≥ 42.0 | 491/500 | 24059/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 91.8000% (459/500) | 8.2000% (41/500) | 0.6286% (154/24500) | ≥ 0.11120139502139982 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 86.8000% (434/500) | 13.2000% (66/500) | 0.8980% (220/24500) | ≥ 13.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 78.8000% (394/500) | 21.2000% (106/500) | 0.8980% (220/24500) | ≥ 14.23171304803726 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.6000% (13/500) | 97.4000% (487/500) | 0.0816% (20/24500) | ≥ 2.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 1.4000% (7/500) | 98.6000% (493/500) | 0.8898% (218/24500) | ≥ 1.9659647941589355 | 500/500 | 24500/24500 |

#### SD300B

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.8000% (489/500) | 2.2000% (11/500) | 0.9143% (224/24500) | ≥ 32.0 | 490/500 | 24010/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 91.2000% (456/500) | 8.8000% (44/500) | 0.9510% (233/24500) | ≥ 0.1093517519137056 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 87.2000% (436/500) | 12.8000% (64/500) | 0.9347% (229/24500) | ≥ 13.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 77.6000% (388/500) | 22.4000% (112/500) | 0.9755% (239/24500) | ≥ 13.909871737732695 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.8000% (9/500) | 98.2000% (491/500) | 0.0980% (24/24500) | ≥ 2.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 1.2000% (6/500) | 98.8000% (494/500) | 0.8571% (210/24500) | ≥ 1.9657549262046814 | 500/500 | 24500/24500 |

#### SD300C

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 98.0000% (490/500) | 2.0000% (10/500) | 0.1878% (46/24500) | ≥ 41.0 | 492/500 | 24108/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 92.8000% (464/500) | 7.2000% (36/500) | 0.9755% (239/24500) | ≥ 0.1081212765565214 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 88.2000% (441/500) | 11.8000% (59/500) | 0.8857% (217/24500) | ≥ 13.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 76.2000% (381/500) | 23.8000% (119/500) | 0.9673% (237/24500) | ≥ 13.93223117984327 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.6000% (8/500) | 98.4000% (492/500) | 0.1143% (28/24500) | ≥ 2.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 1.2000% (6/500) | 98.8000% (494/500) | 0.8571% (210/24500) | ≥ 1.9660930037498474 | 500/500 | 24500/24500 |

#### pooled

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.8000% (1467/1500) | 2.2000% (33/1500) | 0.9238% (679/73500) | ≥ 32.0 | 1473/1500 | 72177/73500 |
| NBIS MINDTCT + MCC SDK v2.0 | 91.8000% (1377/1500) | 8.2000% (123/1500) | 0.9837% (723/73500) | ≥ 0.10868215593466943 | 1500/1500 | 73500/73500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 87.4000% (1311/1500) | 12.6000% (189/1500) | 0.9061% (666/73500) | ≥ 13.0 | 1500/1500 | 73500/73500 |
| SourceAFIS Java 3.18.1 | 77.5333% (1163/1500) | 22.4667% (337/1500) | 0.9646% (709/73500) | ≥ 13.909871737732695 | 1500/1500 | 73500/73500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.0000% (30/1500) | 98.0000% (1470/1500) | 0.0980% (72/73500) | ≥ 2.0 | 1500/1500 | 73500/73500 |
| FLX DeepPrint TexMinu 512 without localization | 1.2667% (19/1500) | 98.7333% (1481/1500) | 0.8857% (651/73500) | ≥ 1.9657549262046814 | 1500/1500 | 73500/73500 |

### FAR target ≤ 1/10000

#### SD300A

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.0000% (485/500) | 3.0000% (15/500) | 0.0000% (0/24500) | ≥ 62.0 | 491/500 | 24059/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 82.8000% (414/500) | 17.2000% (86/500) | 0.0082% (2/24500) | ≥ 0.13089089736886614 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 78.6000% (393/500) | 21.4000% (107/500) | 0.0082% (2/24500) | ≥ 21.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 72.6000% (363/500) | 27.4000% (137/500) | 0.0082% (2/24500) | ≥ 31.350661294812717 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 0.8000% (4/500) | 99.2000% (496/500) | 0.0041% (1/24500) | ≥ 4.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/500) | 100.0000% (500/500) | 0.0000% (0/24500) | accept none | 500/500 | 24500/24500 |

#### SD300B

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.0000% (485/500) | 3.0000% (15/500) | 0.0000% (0/24500) | ≥ 65.0 | 490/500 | 24010/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 82.8000% (414/500) | 17.2000% (86/500) | 0.0082% (2/24500) | ≥ 0.13451194347631443 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 78.0000% (390/500) | 22.0000% (110/500) | 0.0000% (0/24500) | ≥ 22.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 69.8000% (349/500) | 30.2000% (151/500) | 0.0082% (2/24500) | ≥ 31.650359667812804 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 0.4000% (2/500) | 99.6000% (498/500) | 0.0000% (0/24500) | ≥ 5.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/500) | 100.0000% (500/500) | 0.0000% (0/24500) | accept none | 500/500 | 24500/24500 |

#### SD300C

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.0000% (485/500) | 3.0000% (15/500) | 0.0041% (1/24500) | ≥ 61.0 | 492/500 | 24108/24500 |
| NBIS MINDTCT + MCC SDK v2.0 | 85.8000% (429/500) | 14.2000% (71/500) | 0.0082% (2/24500) | ≥ 0.12923149870889264 | 500/500 | 24500/24500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 78.6000% (393/500) | 21.4000% (107/500) | 0.0041% (1/24500) | ≥ 23.0 | 500/500 | 24500/24500 |
| SourceAFIS Java 3.18.1 | 70.0000% (350/500) | 30.0000% (150/500) | 0.0082% (2/24500) | ≥ 30.879122319805724 | 500/500 | 24500/24500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.4000% (7/500) | 98.6000% (493/500) | 0.0000% (0/24500) | ≥ 3.0 | 500/500 | 24500/24500 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/500) | 100.0000% (500/500) | 0.0000% (0/24500) | accept none | 500/500 | 24500/24500 |

#### pooled

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| VeriFinger 2025.2 | 97.0000% (1455/1500) | 3.0000% (45/1500) | 0.0014% (1/73500) | ≥ 61.0 | 1473/1500 | 72177/73500 |
| NBIS MINDTCT + MCC SDK v2.0 | 83.6000% (1254/1500) | 16.4000% (246/1500) | 0.0095% (7/73500) | ≥ 0.13140129855882177 | 1500/1500 | 73500/73500 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 78.1333% (1172/1500) | 21.8667% (328/1500) | 0.0054% (4/73500) | ≥ 22.0 | 1500/1500 | 73500/73500 |
| SourceAFIS Java 3.18.1 | 70.8667% (1063/1500) | 29.1333% (437/1500) | 0.0095% (7/73500) | ≥ 31.12343423621331 | 1500/1500 | 73500/73500 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 0.6000% (9/1500) | 99.4000% (1491/1500) | 0.0027% (2/73500) | ≥ 4.0 | 1500/1500 | 73500/73500 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/1500) | 100.0000% (1500/1500) | 0.0000% (0/73500) | accept none | 1500/1500 | 73500/73500 |

## Secondary view — common-score population

Membership: pairs_scored_by_every_roster_method — 1473 genuine and 72177 impostor pairs scored by every roster method. This view is secondary only; the all-attempt view above is the primary result.

### FAR target ≤ 1/1000 (primary)

#### SD300A

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 76.9857% (378/491) | 23.0143% (113/491) | 0.0998% (24/24059) | ≥ 24.19027129743923 | 491/491 | 24059/24059 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 83.5031% (410/491) | 16.4969% (81/491) | 0.0748% (18/24059) | ≥ 18.0 | 491/491 | 24059/24059 |
| FLX DeepPrint TexMinu 512 without localization | 0.2037% (1/491) | 99.7963% (490/491) | 0.0540% (13/24059) | ≥ 1.9780957102775574 | 491/491 | 24059/24059 |
| VeriFinger 2025.2 | 98.9817% (486/491) | 1.0183% (5/491) | 0.0374% (9/24059) | ≥ 49.0 | 491/491 | 24059/24059 |
| NBIS MINDTCT + MCC SDK v2.0 | 89.4094% (439/491) | 10.5906% (52/491) | 0.0707% (17/24059) | ≥ 0.12013983821960014 | 491/491 | 24059/24059 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.6477% (13/491) | 97.3523% (478/491) | 0.0748% (18/24059) | ≥ 2.0 | 491/491 | 24059/24059 |

#### SD300B

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 75.5102% (370/490) | 24.4898% (120/490) | 0.0625% (15/24010) | ≥ 24.48687767576256 | 490/490 | 24010/24010 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 84.6939% (415/490) | 15.3061% (75/490) | 0.0708% (17/24010) | ≥ 18.0 | 490/490 | 24010/24010 |
| FLX DeepPrint TexMinu 512 without localization | 0.2041% (1/490) | 99.7959% (489/490) | 0.0333% (8/24010) | ≥ 1.9793428182601929 | 490/490 | 24010/24010 |
| VeriFinger 2025.2 | 99.3878% (487/490) | 0.6122% (3/490) | 0.0708% (17/24010) | ≥ 46.0 | 490/490 | 24010/24010 |
| NBIS MINDTCT + MCC SDK v2.0 | 89.1837% (437/490) | 10.8163% (53/490) | 0.0875% (21/24010) | ≥ 0.11868253630155352 | 490/490 | 24010/24010 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.8367% (9/490) | 98.1633% (481/490) | 0.1000% (24/24010) | ≥ 2.0 | 490/490 | 24010/24010 |

#### SD300C

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 73.5772% (362/492) | 26.4228% (130/492) | 0.0705% (17/24108) | ≥ 24.11070116891654 | 492/492 | 24108/24108 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 84.5528% (416/492) | 15.4472% (76/492) | 0.0996% (24/24108) | ≥ 17.0 | 492/492 | 24108/24108 |
| FLX DeepPrint TexMinu 512 without localization | 0.2033% (1/492) | 99.7967% (491/492) | 0.0207% (5/24108) | ≥ 1.9797134399414062 | 492/492 | 24108/24108 |
| VeriFinger 2025.2 | 99.1870% (488/492) | 0.8130% (4/492) | 0.0539% (13/24108) | ≥ 48.0 | 492/492 | 24108/24108 |
| NBIS MINDTCT + MCC SDK v2.0 | 90.0407% (443/492) | 9.9593% (49/492) | 0.0747% (18/24108) | ≥ 0.11940436835824061 | 492/492 | 24108/24108 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.4228% (7/492) | 98.5772% (485/492) | 0.0000% (0/24108) | ≥ 3.0 | 492/492 | 24108/24108 |

#### pooled

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 75.4922% (1112/1473) | 24.5078% (361/1473) | 0.0998% (72/72177) | ≥ 23.379102652238423 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 84.1819% (1240/1473) | 15.8181% (233/1473) | 0.0693% (50/72177) | ≥ 18.0 | 1473/1473 | 72177/72177 |
| FLX DeepPrint TexMinu 512 without localization | 0.2037% (3/1473) | 99.7963% (1470/1473) | 0.0416% (30/72177) | ≥ 1.9780957102775574 | 1473/1473 | 72177/72177 |
| VeriFinger 2025.2 | 99.1853% (1461/1473) | 0.8147% (12/1473) | 0.0720% (52/72177) | ≥ 46.0 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT + MCC SDK v2.0 | 89.6130% (1320/1473) | 10.3870% (153/1473) | 0.0998% (72/72177) | ≥ 0.11837092281048064 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.0367% (30/1473) | 97.9633% (1443/1473) | 0.0970% (70/72177) | ≥ 2.0 | 1473/1473 | 72177/72177 |

### FAR target ≤ 1/100

#### SD300A

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 79.8371% (392/491) | 20.1629% (99/491) | 0.9103% (219/24059) | ≥ 14.23171304803726 | 491/491 | 24059/24059 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 87.9837% (432/491) | 12.0163% (59/491) | 0.9144% (220/24059) | ≥ 13.0 | 491/491 | 24059/24059 |
| FLX DeepPrint TexMinu 512 without localization | 1.4257% (7/491) | 98.5743% (484/491) | 0.8936% (215/24059) | ≥ 1.9659647941589355 | 491/491 | 24059/24059 |
| VeriFinger 2025.2 | 99.3890% (488/491) | 0.6110% (3/491) | 0.1455% (35/24059) | ≥ 42.0 | 491/491 | 24059/24059 |
| NBIS MINDTCT + MCC SDK v2.0 | 92.6680% (455/491) | 7.3320% (36/491) | 0.4863% (117/24059) | ≥ 0.11120139502139982 | 491/491 | 24059/24059 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.6477% (13/491) | 97.3523% (478/491) | 0.0748% (18/24059) | ≥ 2.0 | 491/491 | 24059/24059 |

#### SD300B

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 78.7755% (386/490) | 21.2245% (104/490) | 0.9954% (239/24010) | ≥ 13.909871737732695 | 490/490 | 24010/24010 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 88.5714% (434/490) | 11.4286% (56/490) | 0.9454% (227/24010) | ≥ 13.0 | 490/490 | 24010/24010 |
| FLX DeepPrint TexMinu 512 without localization | 1.2245% (6/490) | 98.7755% (484/490) | 0.8538% (205/24010) | ≥ 1.9657549262046814 | 490/490 | 24010/24010 |
| VeriFinger 2025.2 | 99.7959% (489/490) | 0.2041% (1/490) | 0.9329% (224/24010) | ≥ 32.0 | 490/490 | 24010/24010 |
| NBIS MINDTCT + MCC SDK v2.0 | 93.0612% (456/490) | 6.9388% (34/490) | 0.9996% (240/24010) | ≥ 0.10841617551620115 | 490/490 | 24010/24010 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.8367% (9/490) | 98.1633% (481/490) | 0.1000% (24/24010) | ≥ 2.0 | 490/490 | 24010/24010 |

#### SD300C

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 77.0325% (379/492) | 22.9675% (113/492) | 0.9789% (236/24108) | ≥ 13.93223117984327 | 492/492 | 24108/24108 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 89.0244% (438/492) | 10.9756% (54/492) | 0.8918% (215/24108) | ≥ 13.0 | 492/492 | 24108/24108 |
| FLX DeepPrint TexMinu 512 without localization | 1.2195% (6/492) | 98.7805% (486/492) | 0.8711% (210/24108) | ≥ 1.9660930037498474 | 492/492 | 24108/24108 |
| VeriFinger 2025.2 | 99.5935% (490/492) | 0.4065% (2/492) | 0.1908% (46/24108) | ≥ 41.0 | 492/492 | 24108/24108 |
| NBIS MINDTCT + MCC SDK v2.0 | 93.6992% (461/492) | 6.3008% (31/492) | 0.9374% (226/24108) | ≥ 0.10791000002628323 | 492/492 | 24108/24108 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.6260% (8/492) | 98.3740% (484/492) | 0.1161% (28/24108) | ≥ 2.0 | 492/492 | 24108/24108 |

#### pooled

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 78.5472% (1157/1473) | 21.4528% (316/1473) | 0.9795% (707/72177) | ≥ 13.909871737732695 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 88.5268% (1304/1473) | 11.4732% (169/1473) | 0.9172% (662/72177) | ≥ 13.0 | 1473/1473 | 72177/72177 |
| FLX DeepPrint TexMinu 512 without localization | 1.2899% (19/1473) | 98.7101% (1454/1473) | 0.8909% (643/72177) | ≥ 1.9657549262046814 | 1473/1473 | 72177/72177 |
| VeriFinger 2025.2 | 99.5927% (1467/1473) | 0.4073% (6/1473) | 0.9407% (679/72177) | ≥ 32.0 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT + MCC SDK v2.0 | 93.0754% (1371/1473) | 6.9246% (102/1473) | 0.9671% (698/72177) | ≥ 0.1081212765565214 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 2.0367% (30/1473) | 97.9633% (1443/1473) | 0.0970% (70/72177) | ≥ 2.0 | 1473/1473 | 72177/72177 |

### FAR target ≤ 1/10000

#### SD300A

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 73.5234% (361/491) | 26.4766% (130/491) | 0.0083% (2/24059) | ≥ 31.350661294812717 | 491/491 | 24059/24059 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 80.0407% (393/491) | 19.9593% (98/491) | 0.0083% (2/24059) | ≥ 21.0 | 491/491 | 24059/24059 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/491) | 100.0000% (491/491) | 0.0000% (0/24059) | accept none | 491/491 | 24059/24059 |
| VeriFinger 2025.2 | 98.7780% (485/491) | 1.2220% (6/491) | 0.0000% (0/24059) | ≥ 62.0 | 491/491 | 24059/24059 |
| NBIS MINDTCT + MCC SDK v2.0 | 84.5214% (415/491) | 15.4786% (76/491) | 0.0083% (2/24059) | ≥ 0.12950073902018955 | 491/491 | 24059/24059 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 0.8147% (4/491) | 99.1853% (487/491) | 0.0042% (1/24059) | ≥ 4.0 | 491/491 | 24059/24059 |

#### SD300B

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 70.8163% (347/490) | 29.1837% (143/490) | 0.0083% (2/24010) | ≥ 31.650359667812804 | 490/490 | 24010/24010 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 79.5918% (390/490) | 20.4082% (100/490) | 0.0000% (0/24010) | ≥ 22.0 | 490/490 | 24010/24010 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/490) | 100.0000% (490/490) | 0.0000% (0/24010) | accept none | 490/490 | 24010/24010 |
| VeriFinger 2025.2 | 98.9796% (485/490) | 1.0204% (5/490) | 0.0000% (0/24010) | ≥ 65.0 | 490/490 | 24010/24010 |
| NBIS MINDTCT + MCC SDK v2.0 | 86.9388% (426/490) | 13.0612% (64/490) | 0.0083% (2/24010) | ≥ 0.12934142314295674 | 490/490 | 24010/24010 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 0.4082% (2/490) | 99.5918% (488/490) | 0.0000% (0/24010) | ≥ 5.0 | 490/490 | 24010/24010 |

#### SD300C

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 70.7317% (348/492) | 29.2683% (144/492) | 0.0083% (2/24108) | ≥ 30.879122319805724 | 492/492 | 24108/24108 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 79.8780% (393/492) | 20.1220% (99/492) | 0.0041% (1/24108) | ≥ 23.0 | 492/492 | 24108/24108 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/492) | 100.0000% (492/492) | 0.0000% (0/24108) | accept none | 492/492 | 24108/24108 |
| VeriFinger 2025.2 | 98.5772% (485/492) | 1.4228% (7/492) | 0.0041% (1/24108) | ≥ 61.0 | 492/492 | 24108/24108 |
| NBIS MINDTCT + MCC SDK v2.0 | 86.7886% (427/492) | 13.2114% (65/492) | 0.0083% (2/24108) | ≥ 0.12923149870889264 | 492/492 | 24108/24108 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 1.4228% (7/492) | 98.5772% (485/492) | 0.0000% (0/24108) | ≥ 3.0 | 492/492 | 24108/24108 |

#### pooled

| Method | TAR | FRR | Observed FAR | Score cut (own scale) | Genuine scored/planned | Impostor scored/planned |
|---|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | 71.7583% (1057/1473) | 28.2417% (416/1473) | 0.0097% (7/72177) | ≥ 31.12343423621331 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | 79.5655% (1172/1473) | 20.4345% (301/1473) | 0.0055% (4/72177) | ≥ 22.0 | 1473/1473 | 72177/72177 |
| FLX DeepPrint TexMinu 512 without localization | 0.0000% (0/1473) | 100.0000% (1473/1473) | 0.0000% (0/72177) | accept none | 1473/1473 | 72177/72177 |
| VeriFinger 2025.2 | 98.7780% (1455/1473) | 1.2220% (18/1473) | 0.0014% (1/72177) | ≥ 61.0 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT + MCC SDK v2.0 | 86.0828% (1268/1473) | 13.9172% (205/1473) | 0.0083% (6/72177) | ≥ 0.12923149870889264 | 1473/1473 | 72177/72177 |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | 0.6110% (9/1473) | 99.3890% (1464/1473) | 0.0028% (2/72177) | ≥ 4.0 | 1473/1473 | 72177/72177 |

## Context — native documented rules

Where an upstream author documents a decision rule, the observed outcome at that rule is shown for context. These operating points were chosen by different documents on different scales; ranking algorithms against each other on this table is forbidden.

| Method | Documented rule | Scope | TAR | FRR | Observed FAR |
|---|---|---|---|---|---|
| SourceAFIS Java 3.18.1 | score_greater_than_or_equal_to_40 | SD300A | 67.2000% (336/500) | 32.8000% (164/500) | 0.0000% (0/24500) |
| SourceAFIS Java 3.18.1 | score_greater_than_or_equal_to_40 | SD300B | 64.8000% (324/500) | 35.2000% (176/500) | 0.0000% (0/24500) |
| SourceAFIS Java 3.18.1 | score_greater_than_or_equal_to_40 | SD300C | 63.8000% (319/500) | 36.2000% (181/500) | 0.0000% (0/24500) |
| SourceAFIS Java 3.18.1 | score_greater_than_or_equal_to_40 | pooled | 65.2667% (979/1500) | 34.7333% (521/1500) | 0.0000% (0/73500) |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | score_greater_than_40 | SD300A | 60.2000% (301/500) | 39.8000% (199/500) | 0.0000% (0/24500) |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | score_greater_than_40 | SD300B | 60.8000% (304/500) | 39.2000% (196/500) | 0.0000% (0/24500) |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | score_greater_than_40 | SD300C | 60.0000% (300/500) | 40.0000% (200/500) | 0.0000% (0/24500) |
| NBIS MINDTCT 5.0.0 + BOZORTH3 | score_greater_than_40 | pooled | 60.3333% (905/1500) | 39.6667% (595/1500) | 0.0000% (0/73500) |
| FLX DeepPrint TexMinu 512 without localization | none | — | — | — | — |
| VeriFinger 2025.2 | none_unless_formally_authorized_as_native_documented_rule | — | — | — | — |
| NBIS MINDTCT + MCC SDK v2.0 | none | — | — | — | — |
| NBIS MINDTCT + OpenAFIS (capacity-extended) | none | — | — | — | — |

## Disclosures

- SD300A, SD300B and SD300C are digitizations at different resolutions of the same physical fingerprint cards; they are not independent biometric populations or three independent experiments.
- Pooled rows sum numerators and denominators across the three releases; they are a descriptive summary, not an average of release rates and not a fourth independent experiment.
- The legacy negative population (“same-subject different-finger negative sanity”) is not used as a FAR denominator anywhere in this report.
- SELF comparisons are diagnostic only; no eligibility filtering is applied to any population in this report.
- No calibration was performed, no operational threshold was created, no score was normalized, and no raw score was compared across algorithms in producing this report.
