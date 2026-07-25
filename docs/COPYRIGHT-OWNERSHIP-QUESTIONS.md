# Neural Extractor copyright ownership questions

Status: **HOLD — owner response and qualified legal review required**  
Application version reviewed: **3.0.8**  
Review basis: local files available on **2026-07-22**

This is an engineering evidence record, not legal advice. It deliberately does
not identify a legal copyright owner, infer an assignment, or authorize public
distribution. The root `LICENSE` must retain `Copyright-owner-status: HOLD`, and
the release gate must remain fail-closed, until the questions below have been
answered by an authorized rightsholder and reviewed by qualified counsel.

## Evidence inspected

- `LICENSE`;
- `pyproject.toml`, `README.md`, `main.py`, `NeuralExtractorV3.spec`, and the
  current package source under `src/neural_extractor_v3/`;
- current package metadata and dependency locks present in the project;
- `THIRD_PARTY_LICENSES.txt`, `THIRD_PARTY_NOTICES.md`, and the compliance
  documents under `docs/`;
- release notes for 3.0.4 through 3.0.8 and the local 3.0.3 reliability notes;
- local distribution artifacts, manifests, and checksum files under `dist/`;
- local Git reflog and tag-ref files read directly from `.git/logs/` and
  `.git/refs/tags/` without invoking Git or contacting a remote service.

No contributor agreement, copyright assignment, employment/work-for-hire
record, contractor agreement, corporate registration record, or explicit
relicensing authorization was found among the inspected project files. Absence
from this working copy does not prove that such a record does not exist
elsewhere.

## Facts confirmed by the local files

| Evidence | Exact local fact | What the fact does not establish |
|---|---|---|
| Root `LICENSE` | Declares the MIT License, states `Copyright-owner-status: HOLD`, and preserves the historical string `Copyright (c) Neuralshield & 0xRootNull` without a year. | The legal identity of either name, ownership, year, rights chain, or authority to license. |
| `pyproject.toml` | Declares project `neural-extractor-v3` version `3.0.8`, `license = {text = "MIT"}`, author display name `Neuralshield & 0xRootNull`, and the MIT classifier. | That the metadata author is a legal person, rightsholder, or authorized licensing agent. |
| `README.md` | Names the product “Neural Extractor V3” and repository `AegisAI-Dev/NeuralExtractor`; it contains no project copyright-owner or year statement. | Ownership of the repository account, product name, source, or released binaries. |
| Current Python source | No project copyright, author, license, assignment, or year header was found in the Python modules. Runtime identifiers use `Neuralshield` as an organization/settings name. | That `Neuralshield` is a legal entity or owns the code. A runtime organization string is not title evidence. |
| Current notices | `THIRD_PARTY_LICENSES.txt` and `THIRD_PARTY_NOTICES.md` both record the application owner/year as unresolved and distribution as HOLD. | Resolution of the underlying ownership questions. |
| Local reflog | Commit records use the display identity `0xRootNull` and a GitHub noreply address. Commit messages mention V3.0.0 and V3.0.2 through V3.0.7 releases. | The natural or legal person behind the account, authorship of every file, assignment, employment status, or legal title. |
| Local tag refs | Tag refs exist for `v3.0.0` and `v3.0.2` through `v3.0.7`; no local `v3.0.1` or `v3.0.8` tag ref was found. | Public release, first publication date, contents of remote assets, or ownership. A tag is not a release ledger. |
| Filesystem/repository names | The working path contains `Neuralshield`; application configuration and a GitHub repository name contain Neuralshield/AegisAI identifiers. | Corporate registration, trade-name ownership, agency, or authority to grant MIT rights. |

The first local reflog entry is an initial commit described as “Release Neural
Extractor V3.0.0”. That description is evidence of a local repository event,
not proof of the legally relevant first public distribution date.

## Exact questions the owner must answer

The response should identify the responding person, the capacity in which that
person answers, the date of the answer, and the documents on which each answer
relies. A bare edit to metadata is not sufficient evidence.

### 1. Legal copyright owner name

1. What is the exact legal name of every person or entity that owns copyright
   in the Neural Extractor-authored source, tests, documentation, build scripts,
   artwork, icons, and other project assets?
2. For each owner, what jurisdiction and registration or personal identity
   evidence distinguishes the owner from a screen name, repository account, or
   project label?
3. Is ownership divided by file, contribution, version, or date? If so, provide
   the exact allocation.
4. Who is authorized to approve licensing and distribution for every owner, and
   what evidence establishes that authority?

### 2. Status of “Neuralshield”

1. Is `Neuralshield` a registered legal entity, a registered or unregistered
   trade name, a sole-proprietor business name, or only a project/product name?
2. If it is a legal entity, provide its exact registered name, jurisdiction,
   registration identifier, and the authority of the person approving this
   release.
3. If it is a trade or project name, identify the legal person or entity that
   owns the relevant copyrights and controls use of the name.
4. Was any project material created by employees or contractors for
   Neuralshield? If yes, provide the applicable employment, work-for-hire, or
   assignment terms and their territorial scope.

### 3. Status and rights of “0xRootNull”

1. What legal person or entity does the display name `0xRootNull` identify for
   this project?
2. Which exact files or contributions were created by that person or entity?
3. Does 0xRootNull still own those rights, jointly own them, or have they been
   assigned? Identify the assignee, effective date, scope, territory, and signed
   evidence for any assignment.
4. If no assignment occurred, what license did 0xRootNull grant, to whom, and
   does it expressly authorize MIT licensing, sublicensing, modification, and
   public binary/source distribution?
5. Does the GitHub noreply identity appearing in the local reflog represent the
   same legal person, and who can attest to that linkage?

### 4. First publication year

1. On what exact date and in what form was Neural Extractor or its relevant
   predecessor first made available outside the copyright owner’s private
   control?
2. Was that event source publication, binary distribution, a private customer
   delivery, or a public release?
3. Which archived release page, asset, invoice/delivery record, or other dated
   evidence proves that event?
4. Is V3 derived from an earlier Neural Extractor/V2 codebase or asset set whose
   first publication year must be retained?

The local `v3.0.0` tag/ref and reflog message are not, by themselves, a
confirmed first-publication date.

### 5. Current copyright year range

1. What year or year range should appear in the project notice for each owner?
2. Should the notice use the first-publication year through the year of the last
   copyrightable change, separate per-owner ranges, or another counsel-approved
   form?
3. Which files or assets require older or different notices to be preserved?
4. Who will approve and maintain the year range for future releases?

### 6. Authorization of all contributions

1. Provide a complete list of non-upstream contributors to Neural
   Extractor-authored code, tests, documentation, build/release automation,
   icons, and assets.
2. For each employee, contractor, external contributor, or copied/reused source,
   identify the applicable assignment, employment term, contributor license,
   inbound open-source license, or other permission.
3. Confirm whether material was reused from earlier Neural Extractor versions or
   another private/public project, and document the rights chain for that
   material.
4. Confirm that all third-party notices and authorship statements have been
   preserved and that no third-party code has been described as project-owned.
5. Identify any contribution for which authorship, provenance, permission, or
   modification history remains uncertain.

### 7. Intentional and authorized MIT licensing

1. Is MIT licensing intentional for all project-owned material in the defined
   Neural Extractor distribution scope?
2. Has every legal owner expressly authorized the MIT grant, including the
   rights to use, copy, modify, merge, publish, distribute, sublicense, and sell?
3. Does that authorization cover prior V3 versions as well as 3.0.8, or only a
   prospective release after a stated date?
4. Which assets, files, trademarks, secrets, or third-party components are
   excluded from the MIT grant?
5. Is the historical combined notice `Neuralshield & 0xRootNull` accurate, or
   should counsel approve separate owner notices?
6. Who has authority to approve any correction to `LICENSE`, package metadata,
   source headers, notices, and prior-release remediation?

## Required owner evidence package

At minimum, the qualified reviewer should receive:

- a signed and dated owner response to every question above;
- legal-entity or identity evidence sufficient to resolve both names;
- contribution and file/asset ownership mapping;
- assignments, contributor agreements, employment/work-for-hire or contractor
  terms, and inbound permissions, as applicable;
- dated evidence of first publication and the approved notice year/range;
- explicit authorization of the intended MIT license and its defined scope;
- an inventory of exceptions and third-party material;
- a decision on whether earlier releases require correction, additional source
  delivery, notice, withdrawal, or another remedy.

Sensitive evidence need not be committed to the repository. Counsel may retain
it separately and record only the approved conclusion and non-sensitive
reference identifier here.

## Release-gate acceptance criteria

Ownership remains **HOLD** unless all of the following are true:

1. every owner and year/range is identified by an authorized response;
2. the contribution and assignment chain covers every project-owned distributed
   file and asset;
3. MIT intent and authority are explicit for the exact release scope;
4. qualified legal review approves the resulting notice and license metadata;
5. `LICENSE`, package metadata, notices, and release material are then updated
   consistently by an authorized owner; and
6. the fail-closed release checks verify the approved values.

Until those conditions are met, neither the legacy bundled-provider 3.0.8 EXE
nor the provider-free 3.0.8 candidate is approved for public distribution.
