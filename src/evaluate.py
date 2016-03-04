#!/usr/bin/env python
from __future__ import division, unicode_literals

import argparse
import cPickle as pickle
import codecs
import collections
import logging
import os
import sys
import time

from config import config
from reader.chemdner_corpus import get_chemdner_gold_ann_set, run_chemdner_evaluation
from reader.genia_corpus import get_genia_gold_ann_set
from reader.mirna_corpus import get_ddi_mirna_gold_ann_set
from reader.mirtext_corpus import get_mirtex_gold_ann_set
from reader.tempEval_corpus import get_thymedata_gold_ann_set

if config.use_chebi:
    from postprocessing import chebi_resolution
    from postprocessing.ssm import get_ssm
from postprocessing.ensemble_ner import EnsembleNER
from classification.results import ResultsNER

def get_gold_ann_set(corpus_type, gold_path, entity_type, pair_type, text_path):
    if corpus_type == "chemdner":
        goldset = get_chemdner_gold_ann_set(gold_path)
    elif corpus_type == "tempeval":
        goldset = get_thymedata_gold_ann_set(gold_path, entity_type, text_path, corpus_type)
    elif corpus_type == "pubmed":
        goldset = get_unique_gold_ann_set(gold_path)
    elif corpus_type == "genia":
        goldset = get_genia_gold_ann_set(gold_path, entity_type)
    elif corpus_type == "ddi-mirna":
        goldset = get_ddi_mirna_gold_ann_set(gold_path, entity_type, pair_type)
    elif corpus_type == "mirtex":
        goldset = get_mirtex_gold_ann_set(gold_path, entity_type)
    return goldset


def get_unique_gold_ann_set(goldann):
    """
    Load a gold standard consisting of a list of unique entities
    :param goldann: path to annotation
    :return: Set of gold standard annotations
    """
    with codecs.open(goldann, 'r', 'utf-8') as goldfile:
        gold = [line.strip() for line in goldfile if line.strip()]
    return gold


def compare_results(offsets, goldoffsets, corpus, getwords=True, evaltype="entity"):
    """
    Compare system results with a gold standard
    :param offsets: system results, offset tuples (did, start, end, text)
    :param goldoffsets: Set with the gold standard annotations (did, start, end [, text])
    :param corpus: Reference corpus
    :return: Lines to write into a report files, set of TPs, FPs and FNs
    """
    #TODO: check if size of offsets and goldoffsets tuples is the same
    report = []
    if not getwords:
        offsets = set([x[:-1] for x in offsets])
        goldoffsets = set([x[:-1] for x in goldoffsets])
    tps = offsets & goldoffsets
    fps = offsets - goldoffsets
    fns = goldoffsets - offsets
    fpreport, fpwords = get_report(fps, corpus, getwords=getwords)
    fnreport, fnwords = get_report(fns, corpus, getwords=getwords)
    tpreport, tpwords = get_report(tps, corpus, getwords=getwords)
    alldocs = set(fpreport.keys())
    alldocs = alldocs.union(fnreport.keys())
    alldocs = alldocs.union(tpreport.keys())
    if getwords:
        report.append("Common FPs")
        fpcounter = collections.Counter(fpwords)
        for w in fpcounter.most_common(10):
            report.append(w[0] + ": " + str(w[1]))
        report.append(">\n")
        report.append("Common FNs")
        fncounter = collections.Counter(fnwords)
        for w in fncounter.most_common(10):
            report.append(w[0] + ": " + str(w[1]))
        report.append(">\n")

    for d in list(alldocs):
        report.append(d)
        if d in tpreport:
            for x in tpreport[d]:
                report.append("TP:%s" % x)
        if d in fpreport:
            for x in fpreport[d]:
                report.append("FP:%s" % x)
        if d in fnreport:
            for x in fnreport[d]:
                report.append("FN:%s" % x)

    return report, tps, fps, fns


def get_report(results, corpus, getwords=True):
    """
        Get more information from CHEMDNER results.
        :return: Lines to write to a report file, word that appear in this set
    """
    # TODO: use only offset tuples (did, start, end, text)
    report = {}
    words = []
    for t in results:
        if t[0] == "":
            did = "0"
        else:
            did = t[0]
        if t[0] != "" and t[0] not in corpus.documents:
            logging.info("this doc is not in the corpus! %s" % t[0])
            continue
        start, end = str(t[1]), str(t[2])
        if getwords:
            # doctext = corpus.documents[x[0]].text

            # if stype == "T":
            #     tokentext = corpus.documents[x[0]].title[start:end]
            # else:
                # tokentext = doctext[start:end]
            tokentext = t[3]
            words.append(tokentext)
        if did not in report:
            report[did] = []
        if getwords:
            line = did + '\t' + start + ":" + end + '\t' + tokentext
        else:
            line = did + '\t' + start + ":" + end
        report[did].append(line)
    for d in report:
        report[d].sort()
    return report, words


def get_list_results(results, models, goldset, ths, rules):
    """
    Write results files considering only unique entities, as well as a report file with basic stats
    :param results: ResultsNER object
    :param models: Base model path
    :param goldset: Set with gold standard annotations
    :param ths: Validation thresholds
    :param rules: Validation rules
    """
    print "saving results to {}".format(results.path + ".tsv")
    allentities = results.corpus.get_unique_results(models, ths, rules)
    print "{} unique entities".format(len(allentities))
    with codecs.open(results.path + "_final.tsv", 'w', 'utf-8') as outfile:
        outfile.write('\n'.join(allentities))
    if goldset:
        lineset = set([("", l.lower(), "1") for l in allentities])
        goldset = set([("", g.lower(), "1") for g in goldset])
        reportlines, tps, fps, fns = compare_results(lineset, goldset, results.corpus, getwords=False)
        with codecs.open(results.path + "_report.txt", 'w', "utf-8") as reportfile:
            reportfile.write("TPs: {!s}\nFPs: {!s}\n FNs: {!s}\n".format(len(tps), len(fps), len(fns)))
            if len(tps) == 0:
                precision = 0
                recall = 0
                fmeasure = 0
            else:
                precision = len(tps)/(len(tps) + len(fps))
                recall = len(tps)/(len(tps) + len(fns))
                fmeasure = (2*precision*recall)/(precision + recall)
            reportfile.write("Precision: {!s}\nRecall: {!s}\n".format(precision, recall))
            print "precision: {}".format(precision)
            print "recall: {}".format(recall)
            print "f-measure: {}".format(fmeasure)
            for line in reportlines:
                reportfile.write(line + '\n')


def get_relations_results(results, model, gold_pairs, ths, rules, compare_text=True):
    system_pairs = []
    pcount = 0
    ptrue = 0
    npairs = 0
    for did in results.corpus.documents:
        npairs += len(results.document_pairs[did].pairs)
        for p in results.document_pairs[did].pairs:
            pcount += 1
            if p.recognized_by.get(model) == 1:
                val = p.validate()
                if val:
                    ptrue += 1
                    pair = (did, (p.entities[0].dstart, p.entities[0].dend), (p.entities[1].dstart, p.entities[1].dend),
                            "{}=>{}".format(p.entities[0].text, p.entities[1].text))
                    system_pairs.append(pair)
    print pcount, ptrue, npairs
    if not compare_text:
        gold_pairs = [(o[0], o[1], o[2], "") for o in gold_pairs]
    reportlines, tps, fps, fns = compare_results(set(system_pairs), gold_pairs, results.corpus, getwords=compare_text)
    with codecs.open(results.path + "_report.txt", 'w', "utf-8") as reportfile:
        print "writing report to {}_report.txt".format(results.path)
        reportfile.write("TPs: {!s}\nFPs: {!s}\nFNs: {!s}\n".format(len(tps), len(fps), len(fns)))
        reportfile.write(">\n")
        if len(tps) == 0:
            precision, recall = 0, 0
        else:
            precision, recall = len(tps)/(len(tps) + len(fps)), len(tps)/(len(tps) + len(fns))
        reportfile.write("Precision: {!s}\nRecall: {!s}\n".format(precision, recall))
        reportfile.write(">\n")
        for line in reportlines:
            reportfile.write(line + '\n')
    print "Precision: {}".format(precision)
    print "Recall: {}".format(recall)
    return precision, recall

def get_results(results, models, gold_offsets, ths, rules, compare_text=True):
    """
    Write a report file with basic stats
    :param results: ResultsNER object
    :param models: Base model path
    :param goldset: Set with gold standard annotations
    :param ths: Validation thresholds
    :param rules: Validation rules
    """
    offsets = results.corpus.get_offsets(models, ths, rules)
    # logging.debug(offsets)
    for o in offsets:
        if o[0] not in results.corpus.documents:
            print "DID not found! {}".format(o[0])
            sys.exit()
    if not compare_text: #e.g. gold standard does not include the original text
        offsets = [(o[0], o[1], o[2], "") for o in offsets]
    # logging.info("system entities: {}; gold entities: {}".format(offsets, gold_offsets))
    reportlines, tps, fps, fns = compare_results(set(offsets), gold_offsets, results.corpus, getwords=compare_text)
    with codecs.open(results.path + "_report.txt", 'w', "utf-8") as reportfile:
        print "writing report to {}_report.txt".format(results.path)
        reportfile.write("TPs: {!s}\nFPs: {!s}\nFNs: {!s}\n".format(len(tps), len(fps), len(fns)))
        reportfile.write(">\n")
        if len(tps) == 0:
            precision = 0
            recall = 0
        else:
            precision = len(tps)/(len(tps) + len(fps))
            recall = len(tps)/(len(tps) + len(fns))
        reportfile.write("Precision: {!s}\nRecall: {!s}\n".format(precision, recall))
        reportfile.write(">\n")
        for line in reportlines:
            reportfile.write(line + '\n')
    print "Precision: {}".format(precision)
    print "Recall: {}".format(recall)
    return precision, recall


def main():
    start_time = time.time()
    parser = argparse.ArgumentParser(description='')
    parser.add_argument("action", default="evaluate",
                      help="Actions to be performed.")
    parser.add_argument("goldstd", default="chemdner_sample",
                      help="Gold standard to be used.",
                      choices=config.paths.keys())
    parser.add_argument("--corpus", dest="corpus",
                      default="data/chemdner_sample_abstracts.txt.pickle",
                      help="format path")
    parser.add_argument("--results", dest="results", help="Results object pickle.")
    parser.add_argument("--models", dest="models", help="model destination path, without extension", default="combined")
    parser.add_argument("--ensemble", dest="ensemble", help="name/path of ensemble classifier", default="combined")
    parser.add_argument("--chebi", dest="chebi", help="Chebi mapping threshold.", default=0, type=float)
    parser.add_argument("--ssm", dest="ssm", help="SSM threshold.", default=0, type=float)
    parser.add_argument("--measure", dest="measure", help="semantic similarity measure", default="simui")
    parser.add_argument("--log", action="store", dest="loglevel", default="WARNING", help="Log level")
    parser.add_argument("--submodels", default="", nargs='+', help="sub types of classifiers"),
    parser.add_argument("--rules", default=[], nargs='+', help="aditional post processing rules")
    parser.add_argument("--features", default=["chebi", "case", "number", "greek", "dashes", "commas", "length", "chemwords", "bow"],
                        nargs='+', help="aditional features for ensemble classifier")
    parser.add_argument("--doctype", dest="doctype", help="type of document to be considered", default="all")
    parser.add_argument("--entitytype", dest="etype", help="type of entities to be considered", default="all")
    parser.add_argument("--pairtype", dest="ptype", help="type of pairs to be considered", default=None)
    parser.add_argument("--external", action="store_true", default=False, help="Run external evaluation script, depends on corpus type")
    options = parser.parse_args()

    numeric_level = getattr(logging, options.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % options.loglevel)
    while len(logging.root.handlers) > 0:
        logging.root.removeHandler(logging.root.handlers[-1])
    logging_format = '%(asctime)s %(levelname)s %(filename)s:%(lineno)s:%(funcName)s %(message)s'
    logging.basicConfig(level=numeric_level, format=logging_format)
    logging.getLogger().setLevel(numeric_level)
    logging.info("Processing action {0} on {1}".format(options.action, options.goldstd))
    logging.info("loading results %s" % options.results + ".pickle")
    if os.path.exists(options.results + ".pickle"):
        results = pickle.load(open(options.results + ".pickle", 'rb'))
        results.path = options.results
    else:
        print "results not found"
        sys.exit()

    if options.action == "combine":
        # add another set of annotations to each sentence, ending in combined
        # each entity from this dataset should have a unique ID and a recognized_by attribute
        results.load_corpus(options.goldstd)
        logging.info("combining results...")
        results.combine_results(options.models, options.models + "_combined")
        results.save(options.results + "_combined.pickle")

    elif options.action in ("evaluate", "evaluate_list"):
        if "annotations" in config.paths[options.goldstd]:
            logging.info("loading gold standard %s" % config.paths[options.goldstd]["annotations"])
            goldset = get_gold_ann_set(config.paths[options.goldstd]["format"], config.paths[options.goldstd]["annotations"],
                                       options.etype, options.ptype, config.paths[options.goldstd]["text"])
        else:
            goldset = None
        logging.info("using thresholds: chebi > {!s} ssm > {!s}".format(options.chebi, options.ssm))
        results.load_corpus(options.goldstd)
        results.path = options.results
        ths = {"chebi": options.chebi, "ssm": options.ssm}
        if options.action == "evaluate":
            if options.ptype:
                get_relations_results(results, options.models, goldset[1], ths, options.rules)
            else:
                get_results(results, options.models, goldset, ths, options.rules)
            #if options.bceval:
            #    write_chemdner_files(results, options.models, goldset, ths, options.rules)
            #    evaluation = run_chemdner_evaluation(config.paths[options.goldstd]["cem"],
            #                                         options.results + ".tsv")
            #    print evaluation
        elif options.action == "evaluate_list": # ignore the spans, the gold standard is a list of unique entities
            get_list_results(results, options.models, goldset, ths, options.rules)

    total_time = time.time() - start_time
    logging.info("Total time: %ss" % total_time)
if __name__ == "__main__":
    main()
