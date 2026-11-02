% replan-storm-plan: the program as sent to tddlog.

% The storm, and what it influences.
0.35::z(miss); 0.45::z(graze); 0.2::z(landfall).
0.75::u(low); 0.2::u(medium); 0.05::u(high) :- z(miss).
0.02::emerg :- z(miss).
0.6::adv(none); 0.3::adv(watch); 0.1::adv(warning) :- z(miss).
0.85::cap(full); 0.12::cap(reduced); 0.03::cap(low) :- z(miss).
0.03::lane_closed :- z(miss).
0.3::u(low); 0.5::u(medium); 0.2::u(high) :- z(graze).
0.25::emerg :- z(graze).
0.15::adv(none); 0.55::adv(watch); 0.3::adv(warning) :- z(graze).
0.35::cap(full); 0.5::cap(reduced); 0.15::cap(low) :- z(graze).
0.15::lane_closed :- z(graze).
0.1::u(low); 0.35::u(medium); 0.55::u(high) :- z(landfall).
0.8::emerg :- z(landfall).
0.05::adv(none); 0.25::adv(watch); 0.7::adv(warning) :- z(landfall).
0.1::cap(full); 0.4::cap(reduced); 0.5::cap(low) :- z(landfall).
0.45::lane_closed :- z(landfall).
0.7::sales(flat); 0.25::sales(up); 0.05::sales(sharp) :- u(low).
0.25::sales(flat); 0.55::sales(up); 0.2::sales(sharp) :- u(medium).
0.08::sales(flat); 0.37::sales(up); 0.55::sales(sharp) :- u(high).
% What the operator observed.
evidence(adv(watch), true).
evidence(cap(reduced), true).
evidence(lane_closed, false).
% Each store and category: a five-point demand, Texas raised by the surge.
0.1::demand(ca_1_foods, 12379); 0.2::demand(ca_1_foods, 13448); 0.4::demand(ca_1_foods, 14280); 0.2::demand(ca_1_foods, 15112); 0.1::demand(ca_1_foods, 16181).
0.1::demand(ca_1_household, 3741); 0.2::demand(ca_1_household, 4236); 0.4::demand(ca_1_household, 4620); 0.2::demand(ca_1_household, 5004); 0.1::demand(ca_1_household, 5499).
0.1::demand(ca_1_hobbies, 1501); 0.2::demand(ca_1_hobbies, 1838); 0.4::demand(ca_1_hobbies, 2100); 0.2::demand(ca_1_hobbies, 2362); 0.1::demand(ca_1_hobbies, 2699).
0.1::demand(ca_2_foods, 10316); 0.2::demand(ca_2_foods, 11207); 0.4::demand(ca_2_foods, 11900); 0.2::demand(ca_2_foods, 12593); 0.1::demand(ca_2_foods, 13484).
0.1::demand(ca_2_household, 3118); 0.2::demand(ca_2_household, 3530); 0.4::demand(ca_2_household, 3850); 0.2::demand(ca_2_household, 4170); 0.1::demand(ca_2_household, 4582).
0.1::demand(ca_2_hobbies, 1251); 0.2::demand(ca_2_hobbies, 1532); 0.4::demand(ca_2_hobbies, 1750); 0.2::demand(ca_2_hobbies, 1968); 0.1::demand(ca_2_hobbies, 2249).
0.1::demand(ca_3_foods, 17685); 0.2::demand(ca_3_foods, 19212); 0.4::demand(ca_3_foods, 20400); 0.2::demand(ca_3_foods, 21588); 0.1::demand(ca_3_foods, 23115).
0.1::demand(ca_3_household, 5345); 0.2::demand(ca_3_household, 6051); 0.4::demand(ca_3_household, 6600); 0.2::demand(ca_3_household, 7149); 0.1::demand(ca_3_household, 7855).
0.1::demand(ca_3_hobbies, 2144); 0.2::demand(ca_3_hobbies, 2626); 0.4::demand(ca_3_hobbies, 3000); 0.2::demand(ca_3_hobbies, 3374); 0.1::demand(ca_3_hobbies, 3856).
0.1::demand(ca_4_foods, 7074); 0.2::demand(ca_4_foods, 7685); 0.4::demand(ca_4_foods, 8160); 0.2::demand(ca_4_foods, 8635); 0.1::demand(ca_4_foods, 9246).
0.1::demand(ca_4_household, 2138); 0.2::demand(ca_4_household, 2420); 0.4::demand(ca_4_household, 2640); 0.2::demand(ca_4_household, 2860); 0.1::demand(ca_4_household, 3142).
0.1::demand(ca_4_hobbies, 858); 0.2::demand(ca_4_hobbies, 1050); 0.4::demand(ca_4_hobbies, 1200); 0.2::demand(ca_4_hobbies, 1350); 0.1::demand(ca_4_hobbies, 1542).
0.1::demand(tx_1_foods, 10116); 0.2::demand(tx_1_foods, 10989); 0.4::demand(tx_1_foods, 11669); 0.2::demand(tx_1_foods, 12348); 0.1::demand(tx_1_foods, 13222) :- u(low).
0.1::demand(tx_1_foods, 11477); 0.2::demand(tx_1_foods, 12469); 0.4::demand(tx_1_foods, 13240); 0.2::demand(tx_1_foods, 14011); 0.1::demand(tx_1_foods, 15002) :- u(medium).
0.1::demand(tx_1_foods, 13423); 0.2::demand(tx_1_foods, 14582); 0.4::demand(tx_1_foods, 15484); 0.2::demand(tx_1_foods, 16385); 0.1::demand(tx_1_foods, 17545) :- u(high).
0.1::demand(tx_1_household, 3034); 0.2::demand(tx_1_household, 3435); 0.4::demand(tx_1_household, 3746); 0.2::demand(tx_1_household, 4058); 0.1::demand(tx_1_household, 4459) :- u(low).
0.1::demand(tx_1_household, 3363); 0.2::demand(tx_1_household, 3807); 0.4::demand(tx_1_household, 4153); 0.2::demand(tx_1_household, 4498); 0.1::demand(tx_1_household, 4942) :- u(medium).
0.1::demand(tx_1_household, 3833); 0.2::demand(tx_1_household, 4340); 0.4::demand(tx_1_household, 4734); 0.2::demand(tx_1_household, 5127); 0.1::demand(tx_1_household, 5634) :- u(high).
0.1::demand(tx_1_hobbies, 1156); 0.2::demand(tx_1_hobbies, 1415); 0.4::demand(tx_1_hobbies, 1617); 0.2::demand(tx_1_hobbies, 1819); 0.1::demand(tx_1_hobbies, 2078) :- u(low).
0.1::demand(tx_1_hobbies, 1073); 0.2::demand(tx_1_hobbies, 1314); 0.4::demand(tx_1_hobbies, 1502); 0.2::demand(tx_1_hobbies, 1689); 0.1::demand(tx_1_hobbies, 1930) :- u(medium).
0.1::demand(tx_1_hobbies, 955); 0.2::demand(tx_1_hobbies, 1170); 0.4::demand(tx_1_hobbies, 1337); 0.2::demand(tx_1_hobbies, 1503); 0.1::demand(tx_1_hobbies, 1718) :- u(high).
0.1::demand(tx_2_foods, 12874); 0.2::demand(tx_2_foods, 13986); 0.4::demand(tx_2_foods, 14851); 0.2::demand(tx_2_foods, 15716); 0.1::demand(tx_2_foods, 16828) :- u(low).
0.1::demand(tx_2_foods, 14607); 0.2::demand(tx_2_foods, 15869); 0.4::demand(tx_2_foods, 16850); 0.2::demand(tx_2_foods, 17832); 0.1::demand(tx_2_foods, 19093) :- u(medium).
0.1::demand(tx_2_foods, 17083); 0.2::demand(tx_2_foods, 18559); 0.4::demand(tx_2_foods, 19706); 0.2::demand(tx_2_foods, 20854); 0.1::demand(tx_2_foods, 22329) :- u(high).
0.1::demand(tx_2_household, 3861); 0.2::demand(tx_2_household, 4371); 0.4::demand(tx_2_household, 4768); 0.2::demand(tx_2_household, 5164); 0.1::demand(tx_2_household, 5674) :- u(low).
0.1::demand(tx_2_household, 4280); 0.2::demand(tx_2_household, 4846); 0.4::demand(tx_2_household, 5285); 0.2::demand(tx_2_household, 5725); 0.1::demand(tx_2_household, 6290) :- u(medium).
0.1::demand(tx_2_household, 4879); 0.2::demand(tx_2_household, 5523); 0.4::demand(tx_2_household, 6024); 0.2::demand(tx_2_household, 6526); 0.1::demand(tx_2_household, 7170) :- u(high).
0.1::demand(tx_2_hobbies, 1471); 0.2::demand(tx_2_hobbies, 1801); 0.4::demand(tx_2_hobbies, 2058); 0.2::demand(tx_2_hobbies, 2315); 0.1::demand(tx_2_hobbies, 2645) :- u(low).
0.1::demand(tx_2_hobbies, 1366); 0.2::demand(tx_2_hobbies, 1673); 0.4::demand(tx_2_hobbies, 1911); 0.2::demand(tx_2_hobbies, 2149); 0.1::demand(tx_2_hobbies, 2456) :- u(medium).
0.1::demand(tx_2_hobbies, 1216); 0.2::demand(tx_2_hobbies, 1489); 0.4::demand(tx_2_hobbies, 1701); 0.2::demand(tx_2_hobbies, 1913); 0.1::demand(tx_2_hobbies, 2186) :- u(high).
0.1::demand(tx_3_foods, 11342); 0.2::demand(tx_3_foods, 12321); 0.4::demand(tx_3_foods, 13083); 0.2::demand(tx_3_foods, 13845); 0.1::demand(tx_3_foods, 14825) :- u(low).
0.1::demand(tx_3_foods, 12869); 0.2::demand(tx_3_foods, 13980); 0.4::demand(tx_3_foods, 14844); 0.2::demand(tx_3_foods, 15709); 0.1::demand(tx_3_foods, 16820) :- u(medium).
0.1::demand(tx_3_foods, 15050); 0.2::demand(tx_3_foods, 16349); 0.4::demand(tx_3_foods, 17360); 0.2::demand(tx_3_foods, 18371); 0.1::demand(tx_3_foods, 19671) :- u(high).
0.1::demand(tx_3_household, 3402); 0.2::demand(tx_3_household, 3851); 0.4::demand(tx_3_household, 4200); 0.2::demand(tx_3_household, 4550); 0.1::demand(tx_3_household, 4999) :- u(low).
0.1::demand(tx_3_household, 3771); 0.2::demand(tx_3_household, 4269); 0.4::demand(tx_3_household, 4656); 0.2::demand(tx_3_household, 5043); 0.1::demand(tx_3_household, 5541) :- u(medium).
0.1::demand(tx_3_household, 4298); 0.2::demand(tx_3_household, 4866); 0.4::demand(tx_3_household, 5307); 0.2::demand(tx_3_household, 5749); 0.1::demand(tx_3_household, 6316) :- u(high).
0.1::demand(tx_3_hobbies, 1296); 0.2::demand(tx_3_hobbies, 1587); 0.4::demand(tx_3_hobbies, 1813); 0.2::demand(tx_3_hobbies, 2039); 0.1::demand(tx_3_hobbies, 2330) :- u(low).
0.1::demand(tx_3_hobbies, 1203); 0.2::demand(tx_3_hobbies, 1473); 0.4::demand(tx_3_hobbies, 1684); 0.2::demand(tx_3_hobbies, 1894); 0.1::demand(tx_3_hobbies, 2164) :- u(medium).
0.1::demand(tx_3_hobbies, 1071); 0.2::demand(tx_3_hobbies, 1312); 0.4::demand(tx_3_hobbies, 1499); 0.2::demand(tx_3_hobbies, 1685); 0.1::demand(tx_3_hobbies, 1926) :- u(high).
0.1::demand(wi_1_foods, 9137); 0.2::demand(wi_1_foods, 9926); 0.4::demand(wi_1_foods, 10540); 0.2::demand(wi_1_foods, 11154); 0.1::demand(wi_1_foods, 11943).
0.1::demand(wi_1_household, 2762); 0.2::demand(wi_1_household, 3126); 0.4::demand(wi_1_household, 3410); 0.2::demand(wi_1_household, 3694); 0.1::demand(wi_1_household, 4058).
0.1::demand(wi_1_hobbies, 1108); 0.2::demand(wi_1_hobbies, 1357); 0.4::demand(wi_1_hobbies, 1550); 0.2::demand(wi_1_hobbies, 1743); 0.1::demand(wi_1_hobbies, 1992).
0.1::demand(wi_2_foods, 12084); 0.2::demand(wi_2_foods, 13128); 0.4::demand(wi_2_foods, 13940); 0.2::demand(wi_2_foods, 14752); 0.1::demand(wi_2_foods, 15796).
0.1::demand(wi_2_household, 3652); 0.2::demand(wi_2_household, 4135); 0.4::demand(wi_2_household, 4510); 0.2::demand(wi_2_household, 4885); 0.1::demand(wi_2_household, 5368).
0.1::demand(wi_2_hobbies, 1465); 0.2::demand(wi_2_hobbies, 1794); 0.4::demand(wi_2_hobbies, 2050); 0.2::demand(wi_2_hobbies, 2306); 0.1::demand(wi_2_hobbies, 2635).
0.1::demand(wi_3_foods, 11200); 0.2::demand(wi_3_foods, 12168); 0.4::demand(wi_3_foods, 12920); 0.2::demand(wi_3_foods, 13672); 0.1::demand(wi_3_foods, 14640).
0.1::demand(wi_3_household, 3385); 0.2::demand(wi_3_household, 3832); 0.4::demand(wi_3_household, 4180); 0.2::demand(wi_3_household, 4528); 0.1::demand(wi_3_household, 4975).
0.1::demand(wi_3_hobbies, 1358); 0.2::demand(wi_3_hobbies, 1663); 0.4::demand(wi_3_hobbies, 1900); 0.2::demand(wi_3_hobbies, 2137); 0.1::demand(wi_3_hobbies, 2442).
% The service fraction of each priority store; the exception rule lowers it.
frac(tx_1_foods, 0.8) :- emerg.
frac(tx_1_foods, 0.9) :- \+ emerg.
frac(tx_2_foods, 0.8) :- emerg.
frac(tx_2_foods, 0.9) :- \+ emerg.
frac(tx_3_foods, 0.8) :- emerg.
frac(tx_3_foods, 0.9) :- \+ emerg.
% A priority store meets the rule when its demand times the fraction fits what it gets.
met_at(K, Q) :- cand(K, Q), demand(K, D), frac(K, F), D =< Q / F + 1.0e-9.
met(K) :- recv(K, Q), demand(K, D), frac(K, F), D =< Q / F + 1.0e-9.
recv(tx_1_foods, 13240).
recv(tx_2_foods, 16850).
recv(tx_3_foods, 14844).
all_met :- met(tx_1_foods), met(tx_2_foods), met(tx_3_foods).
query(met(tx_1_foods)).
query(met(tx_2_foods)).
query(met(tx_3_foods)).
query(all_met).

% tddlog's answers:
%   met(tx_1_foods) = 0.8630697553529918
%   met(tx_2_foods) = 0.8630697553529918
%   met(tx_3_foods) = 0.8630697553529918
%   all_met = 0.755470349580833
