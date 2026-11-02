% forecast-coverage: the program as sent to tddlog.

day(0).
obs(0, 0, 39.57142857142857).
obs(0, 1, 54.69642857142857).
obs(0, 2, 65.05357142857143).
demand(J, D) :- day(I), obs(I, J, D).
floor(0.9).
% A store covers its demand at stock A.
cover(J, A) :- level(J, A), demand(J, D), floor(F), A + 1.0e-8 >= F * D.
all_cover(A, B, C) :- combo(A, B, C), cover(0, A), cover(1, B), cover(2, C).
level(0, 24).
level(0, 36).
level(0, 39).
level(0, 40).
level(1, 33).
level(1, 50).
level(1, 54).
level(1, 55).
level(2, 40).
level(2, 59).
level(2, 65).
level(2, 66).
query(cover(0, 24)).
query(cover(0, 36)).
query(cover(0, 39)).
query(cover(0, 40)).
query(cover(1, 33)).
query(cover(1, 50)).
query(cover(1, 54)).
query(cover(1, 55)).
query(cover(2, 40)).
query(cover(2, 59)).
query(cover(2, 65)).
query(cover(2, 66)).
query(demand(0, _)).
query(demand(1, _)).
query(demand(2, _)).

% tddlog's answers:
%   cover(0,24) = 0.0
%   cover(0,36) = 1.0
%   cover(0,39) = 1.0
%   cover(0,40) = 1.0
%   cover(1,33) = 0.0
%   cover(1,50) = 1.0
%   cover(1,54) = 1.0
%   cover(1,55) = 1.0
%   cover(2,40) = 0.0
%   cover(2,59) = 1.0
%   cover(2,65) = 1.0
%   cover(2,66) = 1.0
%   demand(0,39.57142857142857) = 1.0
%   demand(1,54.69642857142857) = 1.0
%   demand(2,65.05357142857143) = 1.0
