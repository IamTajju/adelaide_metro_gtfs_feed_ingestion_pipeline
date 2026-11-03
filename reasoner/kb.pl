% Student Name: Tahzeeb Ahmed
% Student FAN:  ahme0423
% File:         reasoner/kb.pl
% Date:         01-11-2026
% Description:  Static knowledge: confidence levels, the operator table, actions.
% Usage:        loaded by reasoner/rules.pl

% Confidence levels from best to worst; lower/2 steps one level down.
lower(high, medium).
lower(medium, low).
lower(low, low).

% Live only: confidence when an Adelaide Metro estimate exists
% does it agree with the ML class,
% and is the bus within NEAR_STOPS stops of the asked stop?
operator_confidence(agree, near, high).
operator_confidence(agree, far, medium).
operator_confidence(disagree, near, medium).
operator_confidence(disagree, far, low).

% The recommendations the engine can make.
action_text(hold_bus, 'hold the following bus at this timing point').
action_text(notify_passengers, 'tell passengers at the stop').
action_text(flag_to_operator, 'flag the trip to the operator').
action_text(no_action, 'nothing to do').
