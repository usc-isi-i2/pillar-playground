% PILLAR Replan, toy preset, default rules and evidence. recv/2 gives each
% priority store its chance threshold; met/1 and all_met are the rule's probabilities there.

% Toy: S1-S3 demand is known; S4's is 60, 70 or 80.
demand(s1_units, 50).
demand(s2_units, 40).
demand(s3_units, 45).
0.15::demand(s4_units, 60); 0.55::demand(s4_units, 70); 0.3::demand(s4_units, 80).
% The service fraction of each priority store; the exception rule lowers it.
frac(s1_units, 0.9).
frac(s4_units, 0.9).
% A priority store meets the rule when its demand times the fraction fits what it gets.
met_at(K, Q) :- cand(K, Q), demand(K, D), frac(K, F), D =< Q / F + 1.0e-9.
met(K) :- recv(K, Q), demand(K, D), frac(K, F), D =< Q / F + 1.0e-9.
recv(s1_units, 45.0).
recv(s4_units, 72.0).
all_met :- met(s1_units), met(s4_units).
query(met(s1_units)).
query(met(s4_units)).
query(all_met).
