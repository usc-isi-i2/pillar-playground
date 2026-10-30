% Circuit Copilot, storm scenario, no evidence: the plan A 50/40/31/9, B 0/0/0/50,
% backup 13. holds(p0) is the probability the priority rule holds (0.7).

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
ship(p0, a, s1, 50).
ship(p0, a, s2, 40).
ship(p0, a, s3, 31).
ship(p0, a, s4, 9).
ship(p0, b, s1, 0).
ship(p0, b, s2, 0).
ship(p0, b, s3, 0).
ship(p0, b, s4, 50).
backup(p0, 13).
query(world(_)).
query(holds(p0)).
