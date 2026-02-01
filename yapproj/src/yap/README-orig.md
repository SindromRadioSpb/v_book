yap - Yet Another Parser
===========

yap is yet another parser written in Go. It was implemented to test the hypothesis on Joint Morpho-Syntactic Processing of MRLs in a Transition Based Framework. The parser was written as part Amir More's MSc thesis at IDC Herzliya under the supervision of Dr. Reut Tsarfaty from the Open University of Israel. The models and training regimes have been tuned and improved by Amit Seker from the Open University.

yap contains an implementation of the framework and parser of zpar from Z&N 2011 ([Transition-based Dependency Parsing with Rich Non-local Features by Zhang and Nivre, 2011](http://www.aclweb.org/anthology/P11-2033.pdf)) with flags for precise output parity (i.e. bug replication), trained on the morphologically disambiguated
Modern Hebrew treebank.

A live demo of parsing Hebrew texts is provided [here](http://onlp.openu.org.il/). 

yap is no longer under development. It is currently supported as part of the ONLP lab tool kit.

Publications
------------

A [paper on the morphological analysis and disambiguation aspect for Modern Hebrew
and Universal Dependencies](http://www.aclweb.org/anthology/C/C16/C16-1033.pdf) was presented at COLING 2016.
The complete joint morphosyntactic model, along with  benchmark experiments and error analysis are available in a TACL paper accepted for publication in 2018, to be uploaded soon. 

yap was also used for parsing Hebrew, as well as many other languages, in the following academic studies:
- The ONLP lab at the CoNLL shared Task on Raw-to-Dependencies parsing at CoNLL 2017
- [The ONLP lab at the CoNLL shared Task](http://aclweb.org/anthology/K18-2021) on Raw-to-Dependencies parsing at CoNLL 2018
- [The Hebrew Universal Dependencies Treebank](http://aclweb.org/anthology/W18-6016) at UDW 2018
- [Neural Sentiment Analysis for Hebrew](https://aclanthology.info/papers/C18-1190/c18-1190) at COLING 2018

If you use yap for an academic publication, we'd appreciate a [note](reutts@openu.ac.il).


Licensing Highlights:
---------------------
- The code is provided with a permissive license (apache 2.0), as is, and without warranties. 
- The data and lexicon the parser uses belong to [MILA](http://www.mila.cs.technion.ac.il/) at the Technion
- For *production* use, please check with Prof. Alon Itay from The technion data/lexicon license conditions.

Requirements
-----------
- [http://www.golang.org](Go)
- bzip2
- 4-16 CPU cores
- ~4.5GB RAM for Morphological Disambiguation
- ~2GB RAM for Dependency Parsing

Compilation
-----------
- Download and install Go
- Setup a Go environment:
    - Create a directory (usually per workspace/project) ``mkdir yapproj; cd yapproj``
    - Set ``$GOPATH`` environment variable to your workspace: ``export GOPATH=path/to/yapproj ``
    - In the workspace directory create 3 subdirectories: ``mkdir src pkg bin``
    - cd into the src directory ``cd src``
- Clone the repository in the src folder of the workspace, then:
```
cd yap
go get .
go build .
./yap
```
- Bunzip the Hebrew MD model: ``bunzip2 data/hebmd.b32.bz2``
- Bunzip the Hebrew Dependency Parsing model: ``bunzip2 data/dep.b64.bz2``

You may want to use a go workspace manager or have a shell script to set ``$GOPATH`` to <.../yapproj>

Processing Modern Hebrew
-----------
Currently only Pipeline Morphological Analysis, Disambiguation, and Dependency Parsing 
of pre-tokenized Hebrew text is supported. For Hebrew Morphological Analysis, the input
format should have tokens separated by a newline, with another newline to separate sentences.

The lattice format as output by the analyzer can be used as-is for
disambiguation.

For example:
```
עשרות
אנשים
מגיעים
מתאילנד
...

כך
אמר
ח"כ
...
```

Note: The input must be in UTF-8 encoding. yap will process ISO-8859-* encodings incorrectly.

Commands for morphological analysis and disambiguation:

```
./yap hebma -raw input.raw -out lattices.conll -stream
./yap md -in lattices.conll -om output.conll -stream
```

The output of the morphological disambiguator can be used as input for the dependency parser.
Command for dependency parsing:
```
./yap dep -inl output.conll -oc dep_output.conll
```

Citation
-----------
If you make use of this software for research, we would appreciate the following citation:
```
@InProceedings{moretsarfatycoling2016,
  author = {Amir More and Reut Tsarfaty},
  title = {Data-Driven Morphological Analysis and Disambiguation for Morphologically Rich Languages and Universal Dependencies},
  booktitle = {Proceedings of COLING 2016},
  year = {2016},
  month = {december},
  location = {Osaka}
}
```

HEBLEX, a Morphological Analyzer for Modern Hebrew in yap, relies on a slightly modified version of the BGU Lexicon. Please acknowledge and cite the work on the BGU Lexicon with this citation:
```
@inproceedings{adler06,
    Author = {Adler, Meni and Elhadad, Michael},
    Booktitle = {ACL},
    Crossref = {conf/acl/2006},
    Editor = {Calzolari, Nicoletta and Cardie, Claire and Isabelle, Pierre},
    Ee = {http://aclweb.org/anthology/P06-1084},
    Interhash = {6e302df82f4d7776cc487d5b8623d3db},
    Intrahash = {c7ac3ecfe40d039cd6c9ec855cb432db},
    Keywords = {dblp},
    Publisher = {The Association for Computer Linguistics},
    Timestamp = {2013-08-13T15:11:00.000+0200},
    Title = {An Unsupervised Morpheme-Based HMM for {H}ebrew Morphological
        Disambiguation},
    Url = {http://dblp.uni-trier.de/db/conf/acl/acl2006.html#AdlerE06},
    Year = 2006,
    Bdsk-Url-1 = {http://dblp.uni-trier.de/db/conf/acl/acl2006.html#AdlerE06}}
```

License
-----------
This software is released under the terms of the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0).

The Apache license does not apply to the BGU Lexicon. Please contact Reut Tsarfaty regarding licensing of the lexicon.

Contact
-----------
You may contact me at mygithubuser at gmail or Reut Tsarfaty at reutts at openu dot ac dot il
