% Student Name: Tahzeeb Ahmed
% Student FAN:  ahme0423
% File:         reasoner/test_rules.pl
% Date:         01-11-2026
% Description:  plunit tests of the reasoning rules on hand-written facts.
% Usage:        swipl -q -g run_tests -t halt reasoner/test_rules.pl

:- use_module(library(plunit)).
:- ensure_loaded(rules).

% Thresholds as in shared/config.py.
params :-
    assertz(param(p_warn, 0.3333)), assertz(param(conf_medium, 0.5)),
    assertz(param(near_stops, 3)), assertz(param(early_minutes, -1)),
    assertz(param(late_minutes, 5)).

% Every test starts from no facts but the thresholds.
fresh :- clear, params.

clear :-
    forall(member(F/N, [param/2, row/4, prob/4, has_prev/2, seen_stop/1, in_window/1,
                        timepoint/1, follows/2, eta/3, alert/3]),
           ( functor(Head, F, N), retractall(Head) )).

% Facts are added and removed here, in the module the rules read from;
% assertz inside a test unit would land in the unit's own module.
add(Fact) :- assertz(Fact).
del(Fact) :- retract(Fact).

% A seen, in-window bus with a previous stop and the given probabilities.
bus(Id, Stop, E, O, L) :-
    assertz(row(Id, 'G10', Stop, trip)), assertz(prob(Id, E, O, L)),
    assertz(has_prev(Id, 1)), assertz(in_window(Id)),
    ( seen_stop(Stop) -> true ; assertz(seen_stop(Stop)) ).

:- begin_tests(rules, [cleanup(clear)]).

test(confident_on_time_bus_needs_nothing) :-
    fresh,
    bus(1, s1, 0.05, 0.85, 0.10),
    ml_class(1, on_time), confidence(1, medium),
    \+ warn(1, _), action(1, no_action, _).

test(late_warning_below_the_top_class) :-
    fresh,
    bus(1, s1, 0.05, 0.55, 0.40),
    ml_class(1, on_time), warn(1, late),
    action(1, notify_passengers, 'late warning').

test(early_warning_vetoed_at_a_timing_point) :-
    fresh,
    bus(1, s1, 0.45, 0.50, 0.05), add(timepoint(1)),
    \+ warn(1, early), early_vetoed(1), action(1, no_action, _).

test(missing_previous_stop_caps_confidence) :-
    fresh,
    bus(1, s1, 0.02, 0.95, 0.03),
    del(has_prev(1, 1)), add(has_prev(1, 0)),
    guard(1, no_previous_stop), confidence(1, low).

test(unseen_stop_caps_confidence) :-
    fresh,
    bus(1, s1, 0.02, 0.95, 0.03),
    del(row(1, 'G10', s1, trip)), add(row(1, 'G10', s9, trip)),
    guard(1, unseen_stop), confidence(1, low).

test(outside_window_caps_confidence) :-
    fresh,
    bus(1, s1, 0.02, 0.95, 0.03), del(in_window(1)),
    guard(1, outside_window), confidence(1, low).

test(bunching_when_the_leader_runs_late) :-
    fresh,
    bus(1, s1, 0.05, 0.40, 0.55), bus(2, s1, 0.05, 0.90, 0.05),
    add(follows(2, 1)),
    bunching(1, 2), hold_vetoed(2),
    action(2, notify_passengers, 'bunching: the next bus is right behind').

test(bunching_holds_the_follower_at_a_timing_point) :-
    fresh,
    bus(1, s1, 0.05, 0.40, 0.55), bus(2, s1, 0.05, 0.90, 0.05),
    add(follows(2, 1)), add(timepoint(2)),
    \+ hold_vetoed(2), action(2, hold_bus, _).

test(long_gap_when_the_follower_runs_late) :-
    fresh,
    bus(1, s1, 0.05, 0.90, 0.05), bus(2, s1, 0.05, 0.40, 0.55),
    add(follows(2, 1)),
    long_gap(1, 2), \+ bunching(1, 2).

test(no_pair_rule_without_follows) :-
    fresh,
    bus(1, s1, 0.05, 0.40, 0.55), bus(2, s1, 0.05, 0.90, 0.05),
    \+ bunching(_, _), \+ long_gap(_, _).

test(operator_agrees_near_gives_high) :-
    fresh,
    bus(1, s1, 0.05, 0.25, 0.70), add(eta(1, 7, 2)),
    confidence(1, high), verdict(1, late).

test(operator_disagrees_far_gives_low_and_flags) :-
    fresh,
    bus(1, s1, 0.05, 0.25, 0.70), add(eta(1, 0, 6)),
    confidence(1, low), verdict(1, late),
    action(1, flag_to_operator, _).

test(operator_disagrees_near_trusts_the_operator, [nondet]) :-
    fresh,
    bus(1, s1, 0.05, 0.25, 0.70), add(eta(1, 0, 2)),
    confidence(1, medium), verdict(1, on_time).

test(closure_alert_lowers_confidence_and_notifies) :-
    fresh,
    bus(1, s1, 0.05, 0.85, 0.10), add(alert('G10', closure, s1)),
    confidence(1, low), action(1, notify_passengers, _).

test(answer_has_a_trace) :-
    fresh,
    bus(1, s1, 0.05, 0.55, 0.40),
    answer(1, Answer),
    Answer.action == notify_passengers,
    Answer.warnings == [late],
    length(Answer.trace, N), N >= 3.

:- end_tests(rules).
