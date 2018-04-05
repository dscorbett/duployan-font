## Character classes

* non-joining characters
* consonants
* vowels
* affixes
* steps
* diacritics: DTLS and double mark
* overlaps

## ZWJ sequences

* _ X _ => medial
* _ X => final
* X _ => initial

The topographical forms are forced: if a character does not normally join in one direction, the ZWJ might yet cause it to join.

## GSUB sketch

* Compose some diacritics.
  * C DTLS => C\_DTLS
  * C doubleMark+ => C\_doubleMark+
  * Surviving diacritics are visible spacing base glyphs.
* Validate overlap trees. If anything is wrong, all the controls are converted to dotted square fallbacks.
  * A root is followed by no more than its maximum number of overlap controls.
    * 1 for most consonants
    * 2 for simple voiced consonants
    * 0 for everything else
  * Every overlap control is associated with a valid child.
    * Circular vowels and most consonants are valid.
  * A child has at most one child.
  * A child of a child has no children.
  * A parent and its child are not parallel.
  * A continuing overlap does not descend from a non-continuing overlap or vice versa.
  * Adjacent overlap controls are not both continuing overlaps.
  * A continuing overlap control is not followed by another overlap control.
    * This is not invalid according to UTN #37.
    * It is just to make cursive joining easier.
* Set up mark versions of glyphs in overlap trees for later use in GPOS.
* ligatures and contextual forms 
  * consonant + {} homorganic consonant => slight jog
  * consonant + ZWJ + homorganic consonant => dotted consonant
  * circle vowel } + ZWJ + L (?! circle vowel) => reversed vowel
  * R + ZWJ + { circle vowel => reversed vowel
  * [GK] + { W => hook W
  * O + A => WA (Romanian only?)
  * various forms of Romanian U
* standard variants, probably also with ZWJ
  * R + ZWJ + { L => short tick L
  * L + ZWJ + { R => short tick R
* character variants
  * Pernin: W
  * Perrault: hook W
  * Chinook: M, N, J, S as numbers
  * French Duployan: 4, 6
* topographical features
* orientation
* Reorder affixes.
* nut fractions without visible fraction bar

## GPOS sketch

* cursive joining
* continuing overlap
* non-continuing overlap
* fixed-position diacritics (not in the Duployan block)
* diacritics on non-Duployan bases
* centering the whole stenogram (very tricky)

## Glyph notes

Pernin: Article 8: “The initial or first _up_ stroke in each word should begin on the line,
and the first _down_ stroke should rest on the line.”

Pernin lesson IV gives absolute dimensions for some letters.

Pernin article 33: Digits may be joined to stenograms.

PUP p. 76: “Should _t_ or _d_ follow [overlapping _t_ for ‘trans-’], it is passed over
and the prefix written through the next convenient sign.”

PUP p. 77: “dismiss” is two parallel horizontal lines: U+1BC86 U+1BC96?

SOPU p. 25: digits in Romanian

Romanian M is a medium circle in SOPU
(a different system than the Romanian in the proposal but similar enough to be supported).

S-D: the secant affix (“ex-”) may be shaded to form “exer-”.

S-D: “When two straight strokes come together going in the same direction, make a slight break
between them (without, however, lifting the pen from the paper)”
where one of the French ones (I think) specified a small cross stroke.

## Unanswered questions and unencoded characters

Medial French “ou” is written as a medium circle, like O, without the Ou’s inner tooth.
(Or, according to Perrault, it is like Ow).
Should it be transcribed as O or as Ou/Ow?
The example of Romanian U (whose medial form looks like Ow) suggests it should be Ou.
There is a tooth in the medial form where it is convenient to write, like in TOuS.
But how are we to distinguish “tout de même” from “tout le monde”
(<http://www.musique-ancienne.fr/duploye/TP/abrev/abreviation.html>)?
Perrault-en explicitly says it is a replacement (rule 25) i.e. a different letter.

Are the medial nasals misanalyzed?
UTN #37 says they float by default;
are those floaters just the Perrault-en acute and grave above and below?
In which case, they would have much simpler joining behavior.

Is there any way to distinguish I from E between a curved consonant
and a consonant which would otherwise cross the curved consonant?
<http://www.musique-ancienne.fr/duploye/01/Al_03.html> suggests not (“planète” vs. “nickel”).

How is the underline encoded in the abbreviation for “New York” (NOuRK + underline)?
Proper nouns are underlined, so I suppose this is the same thing.

Similary, some Romanian abbreivations incorporate an equals sign for “aceeași” and “egal”.
“Egalitate” is an equals sign with the bottom line extended right.

Similary, a dot for English “point of view” or Romanian “punct [de vedere]”.

Similarly, multiplication cross for Romanian “multiple”.

Similarly, a northeast arrow for Romanian “in sens”.
Proposed as xB1 ROMANIAN SHORTHAND  SIGN SENS in L2/09-364

Similarly, ideograph of crossing axes for “de-a lungul și de-a latul”.

How should the reverse circle consonant ligatures (not vowels!) from
<http://www.musique-ancienne.fr/duploye/codifie/su1/cercles.html> be encoded?
“Reverse circle vowels are not known to interact typographically with other vowel characters”
is therefore literally true but glyphically false.

Perrault-en says long U is “written in any direction whatever” but code chart says it is invariant.

Sloan-Duployan half-thickened large semicircle

Pernin retracted short vowels via backwards tick

Pernin X: one-third length of F

Pernin punctuation

S-D punctuation: long and short wavy lines

SOPU: small connected “3” is “șt” (ro) or “sh” (en)
It seems to be a double U+1BC7B according to L2/10-202.

## Extra characters used in Duployan

* U+003E GREATER-THAN SIGN: Romanian “mai mare”
* U+003C LESS-THAN SIGN: Romanian “mai mic”
* U+2AA4 GREATER-THAN OVERLAPPING LESS-THAN: Romanian “mai mare sau mai mic”
* subscript “10” in “Marea Revoluție Socialistă din Octombrie”
* U+002B PLUS SIGN: “moarte”, “mort”, “murit”
* U+003F QUESTION MARK: “se pune întrebarea”
* U+003A COLON: “durch” (SOPU-de)
* U+00F7 DIVISION SIGN: “zwischen” (SOPU-de)

## Links

* <http://www.unicode.org/notes/tn37/tn37-10272r2-duployan.pdf>
* <http://www.musique-ancienne.fr/duploye/index.html>
* <http://web.archive.org/web/20120730075329/http://www.stenographie.ch/stenographie_integrale.pdf>
* <http://lepetitstenographe.pagesperso-orange.fr/>
* <http://www.musique-ancienne.fr/stenographie/>
  * Sténographie Aimé Paris, similar to but not Duployan
* <http://web.archive.org/web/20130809144951/http://www.stenographie.ch/fr_introd.html>
* <http://forumsteno.vosforums.com>
  * Semi-active forum in French
* <http://numerique.banq.qc.ca/patrimoine/details/52327/1988503>
  * English Duployan manual by Perrault
* <https://archive.org/stream/reportersrulesab00sloaiala#page/6/mode/2up>
  * Sloan-Duployan
* <https://archive.org/stream/universalphonope00perniala#page/10/mode/2up>
  * Pernin
* <https://archive.org/details/universalphonogr00perniala>
  * Pernin’s Universal Phonography
* <https://www.scribd.com/document/38629841/Curs-de-Stenografie>
  * Curs de Stenographie (Romanian)
* <https://www.scribd.com/document/141920135/Stenografie-Dup-Sistemul-Duploye-Ion-Vasilescu-Pierre-Dephanis>
  * Stenografie: După Sistemul Duployé (Romanian)
  * not available without account
* <https://en.calameo.com/read/00283580922a3b0591cd2>
  * Stenografia, o practică uitată
* <https://www.scribd.com/document/228753422/Sfin%C8%9Bescu-Margareta-Stenografie-F%C4%83r%C4%83-Profesor>
  * Stenografie Fără Profesor
* <http://casafernandopessoa.cm-lisboa.pt/bdigital/6-11/2/6-11_master/6-11_PDF/6-11_0000_1-56_t24-C-R0150.pdf>
  * The Sloan-Duployan Phonographic Instructor
* <http://eco.canadiana.ca/view/oocihm.8_04645_1/4?r=0&s=1>
  * Kamloops Wawa, No. 1
  * No. 2 has more letters’ descriptions.

