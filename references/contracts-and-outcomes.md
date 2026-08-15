# Contracts — state what a unit produces, and check it

Reference catalog entry — load on demand.

**The failure this prevents:** a unit is edited, the whole suite passes, and the thing the unit exists
to produce is destroyed. It happens when tests assert that a collaborator was *called* rather than
that the output is *right* — the collaborator is mocked, so nothing ever looks at what was built.
`expect(mock).toHaveBeenCalled()` proves a call happened. It does not test the unit.

This is the specific way parallel agent sessions break a pipeline. Each one reads the code, sees no
statement of what the stage must produce, changes it plausibly, and gets a green suite.

## What to do

- **At task start, find out whether the project declares outcomes** — a contract registry, acceptance
  criteria, a coverage test that fails when a criterion is untested. If one exists, it is authoritative:
  read the contract for any unit before changing it, and keep every criterion true. If changing what a
  unit produces is the actual intent, change the contract in the same commit and say so.
- **Write the contract before the code** for anything new: what it produces, then the criteria that
  must hold, then a test named after each criterion, then the implementation.
- **Assert the artifact, not the interaction.** Check the thing that was produced.
- **Make coverage mechanical.** A test that fails when a criterion has no test is what keeps this
  alive; a convention alone decays. Pin the debt list at zero so a new unit must arrive with its
  contract rather than a promise to add one later.
- **Mandatory where it is expensive and quiet**: anything spending money on a model, or producing a
  durable artifact. Optional for front-end and pure logic, where being wrong is usually loud.

**Reference implementation:** a personal project's `lib/contracts/unit-contracts.ts` with
`contract-coverage.test.ts`, and its `/new-unit` and `/cover-unit` skills for creating and retrofitting.
Read those before building anything similar elsewhere.
