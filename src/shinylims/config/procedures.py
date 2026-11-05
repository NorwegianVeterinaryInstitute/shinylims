"""Entries shown in the Links & Procedures view.

Edit ``PROCEDURE_ENTRIES`` to add, change, or remove an entry. Entries are
shown grouped by ``category``, in the order they appear here.

Fields used by every entry:
- `id`: Unique key, used to build the button/download IDs. Letters, digits,
  and underscores only.

- `title`: Name shown in the list.

- `description`: One line explaining what the document is for.

- `category`: Group heading the entry is listed under.

- `source`: Where the document lives. Allowed values:

  `github` - a Markdown file in a public GitHub repo. Fetched each time someone
  opens it, so edits on GitHub show up without redeploying the app.
  Requires `url`: the file's normal GitHub link, as copied from the browser
  (``https://github.com/<owner>/<repo>/blob/<branch>/<path>.md``). Use a commit
  SHA instead of the branch name to pin an approved version.

  `ek` - a document in the EK quality system. EK has its own login, so the app
  only links to it. Requires `url`.

  `sharepoint` - a file in SharePoint (or a Teams channel, whose files live in
  SharePoint). Requires `url`: a sharing link from "Copy link" set to people
  in the institute. Upload new versions over the same file so the link keeps
  pointing at the current one. Documents here are expected to move into EK
  once the lab is accredited.

  `link` - any other web page, such as a portal or tool. Requires `url`.
"""

PROCEDURE_SOURCES = ("github", "ek", "sharepoint", "link")

PROCEDURE_ENTRIES = [
    {
        "id": "lablink_portal",
        "title": "LabLink",
        "description": "Our web portal for ordering NGS.",
        "category": "Ordering",
        "source": "link",
        "url": "https://nvi-prod.claritylims.com/lablink/login",
    },
    {
        "id": "ek_lablink_ordering",
        "title": "Bestilling av NGS via nettportalen LabLink",
        "description": "How to order NGS through the LabLink web portal.",
        "category": "Ordering",
        "source": "ek",
        "url": "https://vetinst.dkhosting.no/docs/pub/DOK03585.pdf",
    },
    {
        "id": "te07_042_extraction_bacterial_genomic_dna",
        "title": "Ekstraksjon av bakterielt genomisk DNA til dypsekvensering",
        "description": "Extraction of bacterial genomic DNA for deep sequencing.",
        "category": "Lab methods",
        "source": "ek",
        "url": "https://vetinst.dkhosting.no/docs/pub/DOK03140.pdf",
    },
    {
        "id": "ek_te07_052_tecan_quantification",
        "title": "Kvantifisering av dsDNA ved fluorescens på TecanSpark (TE07_052)",
        "description": "Fluorescence-based dsDNA quantification on the Tecan Spark.",
        "category": "Lab methods",
        "source": "ek",
        "url": "https://vetinst.dkhosting.no/docs/pub/DOK03489.pdf",
    },
    {
        "id": "sp_ampure_xp_hamilton",
        "title": "AMPure XP på Hamilton vha. Illumina Metagenomics-protokollen",
        "description": "AMPure XP bead clean-up on the Hamilton, following the Illumina Metagenomics protocol.",
        "category": "Lab methods",
        "source": "sharepoint",
        "url": "https://vetinst.sharepoint.com/:w:/r/sites/SEQ-TECHwetlab/Delte%20dokumenter/General/ShinyClarity%20docs/Protokoll%20AMPure%20XP%20Hamilton.docx?d=wf68de08d3be449b691eb685fe439d4d5&csf=1&web=1&e=zpCYxc",
    },
    {
        "id": "ek_te07_057_ngs_routine",
        "title": "NGS-rutinen (MiSeq-sekvensering) (TE07_057)",
        "description": "The lab's routine for NGS sequencing on the MiSeq.",
        "category": "Sequencing",
        "source": "ek",
        "url": "https://vetinst.dkhosting.no/docs/pub/DOK03868.pdf",
    },
    {
        "id": "demux_operator_guide",
        "title": "Demultiplexing operator guide",
        "description": "What the demux script does with a finished run, how to follow a run, and what to do when it stops.",
        "category": "Demultiplexing",
        "source": "github",
        "url": "https://github.com/NorwegianVeterinaryInstitute/DemultiplexRawSequenceData/blob/master/docs/operator_guide.md",
    },
    {
        "id": "unlock_bitwarden_seqtech00",
        "title": "Unlock Bitwarden on seqtech00",
        "description": "Needed after seqtech00 reboots or when the demux script reports that Bitwarden is locked.",
        "category": "Demultiplexing",
        "source": "github",
        "url": "https://github.com/NorwegianVeterinaryInstitute/DemultiplexRawSequenceData/blob/master/docs/unlock-bitwarden-on-seqtech00.md",
    },
]
