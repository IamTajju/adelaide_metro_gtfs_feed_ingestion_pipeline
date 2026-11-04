% Student Name: Tahzeeb Ahmed
% Student FAN:  ahme0423
% File:         reasoner/rules.pl
% Date:         01-11-2026
% Description:  Rules that turn ML probabilities and timetable facts into an answer.
% Usage:        consulted by reasoner/run.pl and reasoner/test_rules.pl
%
% Facts come from hybrid_engine/facts.py, one set per query or evaluation run:
%   param(Name, Value).              thresholds from shared/config.py
%   row(Id, Route, Stop, Trip).      one bus at one stop
%   prob(Id, PEarly, POnTime, PLate) the ML probabilities
%   has_prev(Id, 0 or 1).            was the bus seen at its previous chosen stop?
%   seen_stop(Stop).                 the stop occurs in the training data
%   in_window(Id).                   scheduled inside a collection window
%   timepoint(Id).                   this stop is a timing point of the trip
%   follows(B, A).                   B is the next scheduled bus after A at the stop
%   eta(Id, DelayMin, StopsAway).    live only: Adelaide Metro's estimate
%   alert(Route, Type, Stop).        live only: Type closure or detour, Stop or any

:- ensure_loaded(kb).

:- dynamic param/2, row/4, prob/4, has_prev/2, seen_stop/1, in_window/1,
           timepoint/1, follows/2, eta/3, alert/3.

% ---- The ML prediction -------------------------------------------------

ml_class(Id, Class) :-
    prob(Id, E, O, L),
    max_list([E, O, L], Top),
    nth1(Index, [E, O, L], Top), !,
    nth1(Index, [early, on_time, late], Class).

top_prob(Id, Top) :-
    prob(Id, E, O, L),
    max_list([E, O, L], Top).

delay_class(Minutes, early) :- param(early_minutes, E), Minutes < E, !.
delay_class(Minutes, late) :- param(late_minutes, L), Minutes > L, !.
delay_class(_, on_time).

% ---- Warnings ----------------------------------------------------------

% Warn when early or late is more likely than chance, even if it is not the
% top class: a missed late or early bus costs passengers more than a false
% alarm. The same threshold without these rules is the evaluation baseline.
warn(Id, late) :-
    prob(Id, _, _, L), param(p_warn, T), L >= T.
warn(Id, early) :-
    prob(Id, E, _, _), param(p_warn, T), E >= T,
    \+ timepoint(Id).

% At a timing point drivers wait for the scheduled time, so a bus cannot
% leave early there: the early warning is vetoed.
early_vetoed(Id) :-
    prob(Id, E, _, _), param(p_warn, T), E >= T,
    timepoint(Id).

% ---- Guards: when the model is outside what it was trained on ----------

guard(Id, no_previous_stop) :- has_prev(Id, 0).
guard(Id, unseen_stop) :- row(Id, _, Stop, _), \+ seen_stop(Stop).
guard(Id, outside_window) :- \+ in_window(Id).

% ---- Confidence --------------------------------------------------------

% With an operator estimate (live only): the table in kb.pl.
base_confidence(Id, Level, Why) :-
    eta(Id, Delay, Away), !,
    ml_class(Id, Class),
    delay_class(Delay, OperatorClass),
    ( Class == OperatorClass -> Agree = agree ; Agree = disagree ),
    param(near_stops, Near),
    ( Away =< Near -> Distance = near ; Distance = far ),
    operator_confidence(Agree, Distance, Level),
    format(atom(Why), 'operator estimate ~w min (~w) ~ws with ML ~w; bus ~w stops away (~w)',
           [Delay, OperatorClass, Agree, Class, Away, Distance]).
% Without one: by the ML probability alone, never higher than medium.
base_confidence(Id, Level, Why) :-
    top_prob(Id, Top), param(conf_medium, Medium),
    ( Top >= Medium -> Level = medium ; Level = low ),
    format(atom(Why), 'no operator estimate: top ML probability ~2f -> ~w', [Top, Level]).

route_alert(Id, Type) :-
    row(Id, Route, Stop, _),
    alert(Route, Type, Where),
    ( Where == any ; Where == Stop ).

confidence(Id, Level) :-
    base_confidence(Id, Base, _),
    ( guard(Id, _) -> Guarded = low ; Guarded = Base ),
    ( route_alert(Id, _) -> lower(Guarded, Level) ; Level = Guarded ).

% The class the answer states: the operator's when it is trusted, else ML's.
verdict(Id, Class) :-
    eta(Id, Delay, Away), param(near_stops, Near),
    ml_class(Id, MLClass), delay_class(Delay, OperatorClass),
    ( Away =< Near ; OperatorClass == MLClass ), !,
    Class = OperatorClass.
verdict(Id, Class) :- ml_class(Id, Class).

% ---- Bus pairs: what one-trip-at-a-time ML cannot see ------------------

% Bunching: the leader runs late while the follower does not, or the
% follower runs early while the leader does not; the gap closes.
bunching(Leader, Follower) :-
    follows(Follower, Leader),
    (   warn(Leader, late), \+ warn(Follower, late)
    ;   warn(Follower, early), \+ warn(Leader, early)
    ), !.

% Long gap: the mirror case; the gap opens.
long_gap(Leader, Follower) :-
    follows(Follower, Leader),
    (   warn(Leader, early), \+ warn(Follower, early)
    ;   warn(Follower, late), \+ warn(Leader, late)
    ), !.

% Holding only makes sense at a timing point; elsewhere it is vetoed.
hold_vetoed(Id) :- bunching(_, Id), \+ timepoint(Id).

% ---- Recommendation ----------------------------------------------------

action(Id, hold_bus, 'follower of a bunching pair at a timing point') :-
    bunching(_, Id), timepoint(Id), !.
action(Id, notify_passengers, 'bunching: the next bus is right behind') :-
    bunching(_, Id), !.
action(Id, notify_passengers, Why) :-
    route_alert(Id, closure), !,
    format(atom(Why), 'closure alert on the route', []).
action(Id, flag_to_operator, 'operator estimate and ML disagree far from the stop') :-
    base_confidence(Id, low, _), eta(Id, _, _), !.
action(Id, notify_passengers, 'late warning') :- warn(Id, late), !.
action(Id, notify_passengers, 'early warning') :- warn(Id, early), !.
action(Id, notify_passengers, 'long gap: expect a long wait') :- long_gap(_, Id), !.
action(_, no_action, 'no warning').

% ---- The answer with its reasoning trace -------------------------------

trace_line(Id, Line) :-
    prob(Id, E, O, L), ml_class(Id, Class),
    format(atom(Line), 'ML predicts ~w (early ~2f, on_time ~2f, late ~2f)', [Class, E, O, L]).
trace_line(Id, Line) :-
    base_confidence(Id, _, Why), format(atom(Line), 'confidence basis: ~w', [Why]).
trace_line(Id, Line) :-
    guard(Id, Guard),
    format(atom(Line), 'guard: ~w -> confidence capped at low', [Guard]).
trace_line(Id, Line) :-
    route_alert(Id, Type), format(atom(Line), 'alert: ~w on the route -> one level lower', [Type]).
trace_line(Id, Line) :-
    warn(Id, Class), param(p_warn, T),
    format(atom(Line), 'warn ~w: p(~w) >= ~2f', [Class, Class, T]).
trace_line(Id, 'early warning vetoed: timing point, the bus waits for its scheduled time') :-
    early_vetoed(Id).
trace_line(Id, Line) :-
    bunching(Leader, Id), row(Leader, _, _, Trip),
    format(atom(Line), 'bunching with the bus ahead (trip ~w): the gap will close', [Trip]).
trace_line(Id, Line) :-
    long_gap(Leader, Id), row(Leader, _, _, Trip),
    format(atom(Line), 'long gap after the bus ahead (trip ~w): the gap will open', [Trip]).
trace_line(Id, 'hold_bus vetoed: not a timing point') :- hold_vetoed(Id).
trace_line(Id, Line) :-
    action(Id, Action, Why), action_text(Action, Text),
    format(atom(Line), 'action ~w (~w): ~w', [Action, Text, Why]).

answer(Id, _{id: Id, ml_class: MLClass, verdict: Verdict, confidence: Level,
             warnings: Warnings, guards: Guards, early_vetoed: EarlyVetoed,
             bunching_leader: Bunching, long_gap_leader: Gap, hold_vetoed: HoldVetoed,
             action: Action, trace: Trace}) :-
    ml_class(Id, MLClass),
    verdict(Id, Verdict),
    confidence(Id, Level),
    findall(W, warn(Id, W), Warnings),
    findall(G, guard(Id, G), Guards),
    ( early_vetoed(Id) -> EarlyVetoed = true ; EarlyVetoed = false ),
    ( bunching(B, Id) -> Bunching = B ; Bunching = null ),
    ( long_gap(L, Id) -> Gap = L ; Gap = null ),
    ( hold_vetoed(Id) -> HoldVetoed = true ; HoldVetoed = false ),
    action(Id, Action, _),
    findall(Line, trace_line(Id, Line), Trace).
