% forecast-joint: the program as sent to tddlog.

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
combo(24, 33, 66).
combo(24, 50, 66).
combo(24, 54, 66).
combo(24, 55, 66).
combo(36, 33, 66).
combo(36, 50, 59).
combo(36, 50, 65).
combo(36, 50, 66).
combo(36, 54, 59).
combo(36, 54, 65).
combo(36, 54, 66).
combo(36, 55, 59).
combo(36, 55, 65).
combo(36, 55, 66).
combo(39, 33, 66).
combo(39, 50, 59).
combo(39, 50, 65).
combo(39, 50, 66).
combo(39, 54, 59).
combo(39, 54, 65).
combo(39, 54, 66).
combo(39, 55, 59).
combo(39, 55, 65).
combo(39, 55, 66).
combo(40, 33, 66).
combo(40, 50, 59).
combo(40, 50, 65).
combo(40, 50, 66).
combo(40, 54, 59).
combo(40, 54, 65).
combo(40, 54, 66).
combo(40, 55, 59).
combo(40, 55, 65).
combo(40, 55, 66).
query(all_cover(24, 33, 66)).
query(all_cover(24, 50, 66)).
query(all_cover(24, 54, 66)).
query(all_cover(24, 55, 66)).
query(all_cover(36, 33, 66)).
query(all_cover(36, 50, 59)).
query(all_cover(36, 50, 65)).
query(all_cover(36, 50, 66)).
query(all_cover(36, 54, 59)).
query(all_cover(36, 54, 65)).
query(all_cover(36, 54, 66)).
query(all_cover(36, 55, 59)).
query(all_cover(36, 55, 65)).
query(all_cover(36, 55, 66)).
query(all_cover(39, 33, 66)).
query(all_cover(39, 50, 59)).
query(all_cover(39, 50, 65)).
query(all_cover(39, 50, 66)).
query(all_cover(39, 54, 59)).
query(all_cover(39, 54, 65)).
query(all_cover(39, 54, 66)).
query(all_cover(39, 55, 59)).
query(all_cover(39, 55, 65)).
query(all_cover(39, 55, 66)).
query(all_cover(40, 33, 66)).
query(all_cover(40, 50, 59)).
query(all_cover(40, 50, 65)).
query(all_cover(40, 50, 66)).
query(all_cover(40, 54, 59)).
query(all_cover(40, 54, 65)).
query(all_cover(40, 54, 66)).
query(all_cover(40, 55, 59)).
query(all_cover(40, 55, 65)).
query(all_cover(40, 55, 66)).

% tddlog's answers:
%   all_cover(24,33,66) = 0.0
%   all_cover(24,50,66) = 0.0
%   all_cover(24,54,66) = 0.0
%   all_cover(24,55,66) = 0.0
%   all_cover(36,33,66) = 0.0
%   all_cover(36,50,59) = 1.0
%   all_cover(36,50,65) = 1.0
%   all_cover(36,50,66) = 1.0
%   all_cover(36,54,59) = 1.0
%   all_cover(36,54,65) = 1.0
%   all_cover(36,54,66) = 1.0
%   all_cover(36,55,59) = 1.0
%   all_cover(36,55,65) = 1.0
%   all_cover(36,55,66) = 1.0
%   all_cover(39,33,66) = 0.0
%   all_cover(39,50,59) = 1.0
%   all_cover(39,50,65) = 1.0
%   all_cover(39,50,66) = 1.0
%   all_cover(39,54,59) = 1.0
%   all_cover(39,54,65) = 1.0
%   all_cover(39,54,66) = 1.0
%   all_cover(39,55,59) = 1.0
%   all_cover(39,55,65) = 1.0
%   all_cover(39,55,66) = 1.0
%   all_cover(40,33,66) = 0.0
%   all_cover(40,50,59) = 1.0
%   all_cover(40,50,65) = 1.0
%   all_cover(40,50,66) = 1.0
%   all_cover(40,54,59) = 1.0
%   all_cover(40,54,65) = 1.0
%   all_cover(40,54,66) = 1.0
%   all_cover(40,55,59) = 1.0
%   all_cover(40,55,65) = 1.0
%   all_cover(40,55,66) = 1.0
