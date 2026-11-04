% Student Name: Tahzeeb Ahmed
% Student FAN:  ahme0423
% File:         reasoner/run.pl
% Date:         01-11-2026
% Description:  Batch entry point: loads a facts file, prints every answer as JSON.
% Usage:        swipl -q -g main -t halt reasoner/run.pl -- FACTS.pl

:- use_module(library(http/json)).
:- ensure_loaded(rules).

main :-
    current_prolog_flag(argv, [FactsFile | _]),
    load_files(FactsFile, []),
    findall(Answer, (row(Id, _, _, _), answer(Id, Answer)), Answers),
    json_write_dict(current_output, Answers, [width(0)]),
    nl.
