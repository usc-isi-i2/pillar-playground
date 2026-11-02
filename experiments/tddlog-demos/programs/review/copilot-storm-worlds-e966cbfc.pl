% copilot-storm-worlds: the program as sent to tddlog.

% One of three worlds; priors from the storm probability.
0.15::world(normal); 0.55::world(surge); 0.3::world(storm).
demand(normal, 60).
demand(surge, 70).
demand(storm, 80).
% Depot A's shipment to S4 arrives late in the Storm world of the storm scenario.
late(storm).
alpha(0.9).
% Units each plan delivers to S1 and S4 in each world.
recv(P, W, s1, Y) :- world(W), ship(P, a, s1, A), ship(P, b, s1, B), Y is A + B.
a_s4(P, W, A) :- world(W), \+ late(W), ship(P, a, s4, A).
a_s4(P, W, 0) :- world(W), late(W).
recv(P, W, s4, Y) :- a_s4(P, W, A), ship(P, b, s4, B), backup(P, L), Y is A + B + L.
% The priority rule holds in the world that occurs.
holds(P) :- world(W), demand(W, D), alpha(Al),
    recv(P, W, s1, Y1), Y1 + 1.0e-7 >= Al * 50,
    recv(P, W, s4, Y4), Y4 + 1.0e-7 >= Al * D.
evidence(world(surge), true).
query(world(_)).

% tddlog's answers:
%   world(normal) = 0.0
%   world(storm) = 0.0
%   world(surge) = 1.0
