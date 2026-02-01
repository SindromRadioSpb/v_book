package webapi

import (
	"bytes"
	"fmt"
	"github.com/gonuts/commander"
	"log"
	"strings"
	"sync"
	"yap/alg/search"
	"yap/alg/transition"
	transitionmodel "yap/alg/transition/model"
	"yap/app"
	"yap/nlp/format/conll"
	"yap/nlp/format/lattice"
	. "yap/nlp/parser/dependency/transition"
	nlp "yap/nlp/types"
	"yap/util"
	"yap/util/conf"
)

var (
	depBeam *search.Beam
	depLock sync.Mutex
)

func DepParserInitialize(cmd *commander.Command, args []string) {
	var (
		arcSystem     transition.TransitionSystem
		terminalStack int
	)
	arcSystem = &ArcEager{}
	terminalStack = 0
	arcSystem.AddDefaultOracle()
	transitionSystem := transition.TransitionSystem(arcSystem)
	featuresLocation, found := util.LocateFile(app.DepFeaturesFile, app.DEFAULT_CONF_DIRS)
	if !found {
		panic(fmt.Sprintf("Dep features not found"))
	}
	app.DepFeaturesFile = featuresLocation
	labelsLocation, found := util.LocateFile(app.DepLabelsFile, app.DEFAULT_CONF_DIRS)
	if !found {
		panic(fmt.Sprintf("Dep labels not found"))
	}
	app.DepLabelsFile = labelsLocation
	var (
		model *transitionmodel.AvgMatrixSparse = &transitionmodel.AvgMatrixSparse{}
	)
	modelLocation, found := util.LocateFile(app.DepModelName, app.DEFAULT_MODEL_DIRS)
	if !found {
		panic(fmt.Sprintf("Dep model not found"))
	}
	app.DepModelName = modelLocation
	app.DepConfigOut(modelLocation, &search.Beam{}, transitionSystem)
	relations, err := conf.ReadFile(labelsLocation)
	if err != nil {
		panic(fmt.Sprintf("Failed reading Dep labels from file: %v", labelsLocation))
	}
	app.SetupDepEnum(relations.Values)
	arcSystem = &ArcEager{
		ArcStandard: ArcStandard{
			SHIFT:       app.SH.Value(),
			LEFT:        app.LA.Value(),
			RIGHT:       app.RA.Value(),
			Relations:   app.DepERel,
			Transitions: app.DepETrans,
		},
		REDUCE:  app.RE.Value(),
		POPROOT: app.PR.Value(),
	}
	arcSystem.AddDefaultOracle()
	transitionSystem = transition.TransitionSystem(arcSystem)
	log.Println()
	log.Println("Loading features")

	featureSetup, err := transition.LoadFeatureConfFile(featuresLocation)
	if err != nil {
		panic(fmt.Sprintf("Failed reading Dep features from file: %v", featuresLocation))
	}
	extractor := app.SetupExtractor(featureSetup, []byte("A"))
	group, _ := extractor.TransTypeGroups['A']
	formatters := make([]util.Format, len(group.FeatureTemplates))
	for i, formatter := range group.FeatureTemplates {
		formatters[i] = formatter
	}

	log.Println("Found model file", modelLocation, " ... loading model")
	serialization := app.ReadModel(modelLocation)
	model.Deserialize(serialization.WeightModel)
	app.DepEWord = serialization.EWord
	app.DepEPOS = serialization.EPOS
	app.DepEWPOS = serialization.EWPOS
	app.DepEMHost = serialization.EMHost
	app.DepEMSuffix = serialization.EMSuffix
	log.Println("Loaded model")

	conf := &SimpleConfiguration{
		EWord:         app.DepEWord,
		EPOS:          app.DepEPOS,
		EWPOS:         app.DepEWPOS,
		EMHost:        app.DepEMHost,
		EMSuffix:      app.DepEMSuffix,
		ERel:          app.DepERel,
		ETrans:        app.DepETrans,
		TerminalStack: terminalStack,
		TerminalQueue: 0,
	}

	depBeam = &search.Beam{
		TransFunc:            transitionSystem,
		FeatExtractor:        extractor,
		Base:                 conf,
		Model:                model,
		Size:                 app.BeamSize,
		ConcurrentExec:       app.ConcurrentBeam,
		ShortTempAgenda:      true,
		EstimatedTransitions: app.EstimatedBeamTransitions(),
		ScoredStoreDense:     true,
	}
}

func DepParseDisambiguatedLattice(input string) string {
	depLock.Lock()
	log.Println("Reading disambiguated lattice")
	log.Println("input:\n", input)
	reader := strings.NewReader(input)
	lDisamb, lDisambE := lattice.Read(reader, 0)
	if lDisambE != nil {
		panic(fmt.Sprintf("Failed reading raw input - %v", lDisamb))
	}
	internalSents := lattice.Lattice2SentenceCorpus(lDisamb, app.DepEWord, app.DepEPOS, app.DepEWPOS, app.DepEMorphProp, app.DepEMHost, app.DepEMSuffix)
	sents := make([]interface{}, len(internalSents))
	for i, instance := range internalSents {
		sents[i] = instance.(nlp.LatticeSentence).TaggedSentence()
	}
	parsedGraphs := app.Parse(sents, depBeam)
	graphAsConll := conll.Graph2ConllCorpus(parsedGraphs, app.DepEMHost, app.DepEMSuffix)
	buf := new(bytes.Buffer)
	conll.Write(buf, graphAsConll)
	depLock.Unlock()
	return buf.String()
}
