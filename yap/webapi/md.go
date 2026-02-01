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
	"yap/nlp/format/lattice"
	"yap/nlp/format/mapping"
	"yap/nlp/parser/disambig"
	nlp "yap/nlp/types"
	"yap/util"
)

var (
	mdBeam *search.Beam
	mdLock sync.Mutex
)

func MorphDisambiguatorInitialize(cmd *commander.Command, args []string) {
	paramFunc, exists := nlp.MDParams[app.MdParamFuncName]
	if !exists {
		panic(fmt.Sprintf("MD param func %v doesn't exist", app.MdParamFuncName))
	}
	var (
		mdTrans transition.TransitionSystem
		model   *transitionmodel.AvgMatrixSparse = &transitionmodel.AvgMatrixSparse{}
	)
	mdTrans = &disambig.MDTrans{
		ParamFunc: paramFunc,
		UsePOP:    app.UsePOP,
	}
	disambig.UsePOP = app.UsePOP
	transitionSystem := transition.TransitionSystem(mdTrans)
	featuresLocation, found := util.LocateFile(app.MdFeaturesFile, app.DEFAULT_CONF_DIRS)
	if !found {
		panic(fmt.Sprintf("MD features not found"))
	}
	app.MdFeaturesFile = featuresLocation
	modelLocation, found := util.LocateFile(app.MdModelName, app.DEFAULT_MODEL_DIRS)
	if !found {
		panic(fmt.Sprintf("MD model not found"))
	}
	app.MdModelName = modelLocation
	confBeam := &search.Beam{}
	app.MDConfigOut(modelLocation, confBeam, transitionSystem)
	disambig.SwitchFormLemma = !lattice.IGNORE_LEMMA
	app.SetupMDEnum()
	mdTrans.(*disambig.MDTrans).POP = app.POP
	mdTrans.(*disambig.MDTrans).Transitions = app.MdETrans
	mdTrans.AddDefaultOracle()
	featureSetup, err := transition.LoadFeatureConfFile(featuresLocation)
	if err != nil {
		panic(fmt.Sprintf("Failed reading MD feature configuration file [%v]: %v", featuresLocation, err))
	}
	extractor := app.SetupExtractor(featureSetup, []byte("MPL"))
	log.Println()
	nlp.InitOpenParamFamily("HEBTB")
	log.Println()
	log.Println("Found MD model file", modelLocation, " ... loading model")

	serialization := app.ReadModel(modelLocation)
	model.Deserialize(serialization.WeightModel)
	app.MdEWord = serialization.EWord
	app.MdEPOS = serialization.EPOS
	app.MdEWPOS = serialization.EWPOS
	app.MdEMHost = serialization.EMHost
	app.MdEMSuffix = serialization.EMSuffix
	app.MdEMorphProp = serialization.EMorphProp
	app.MdETrans = serialization.ETrans
	app.MdETokens = serialization.ETokens

	mdTrans = &disambig.MDTrans{
		ParamFunc:   paramFunc,
		UsePOP:      app.UsePOP,
		POP:         app.POP,
		Transitions: app.MdETrans,
	}

	transitionSystem = transition.TransitionSystem(mdTrans)
	extractor = app.SetupExtractor(featureSetup, []byte("MPL"))

	conf := &disambig.MDConfig{
		ETokens:     app.MdETokens,
		POP:         app.POP,
		Transitions: app.MdETrans,
		ParamFunc:   paramFunc,
	}

	mdBeam = &search.Beam{
		TransFunc:            transitionSystem,
		FeatExtractor:        extractor,
		Base:                 conf,
		Size:                 app.BeamSize,
		ConcurrentExec:       app.ConcurrentBeam,
		Transitions:          app.MdETrans,
		EstimatedTransitions: 1000, // chosen by random dice roll
	}
	mdBeam.ShortTempAgenda = true
	mdBeam.Model = model
}

func MorphDisambiguateLattices(input string) string {
	mdLock.Lock()
	log.Println("Reading ambiguous lattices")
	log.Println("input:\n ", input)
	reader := strings.NewReader(input)
	lAmb, lAmbE := lattice.Read(reader, 0)
	if lAmbE != nil {
		panic(fmt.Sprintf("Failed reading raw input - %v", lAmbE))
	}
	predAmbLat := lattice.Lattice2SentenceCorpus(lAmb, app.MdEWord, app.MdEPOS, app.MdEWPOS, app.MdEMorphProp, app.MdEMHost, app.MdEMSuffix)
	mappings := app.Parse(predAmbLat, mdBeam)
	buf := new(bytes.Buffer)
	mapping.Write(buf, mappings)
	mdLock.Unlock()
	return buf.String()
}
