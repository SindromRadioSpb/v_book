# Guided reconnect-path guidance phase 2

## Scope

This bounded wave extends reconnect guidance after:

- `Guided onboarding / reconnect UX phase 1`
- `Release / ship gate phase 3`

It does **not** redesign restart flow, DB switching mechanics, or startup
defer logic. It only makes the operator-facing reconnect path clearer in the
existing UI.

## Entry points

- `app/ui/app_window.py`
- `app/ui/database_switch_dialog.py`
- `app/ui/first_run_wizard.py`

## Product problem

After cold closure and lower-layer recovery, operators could already:

- start on the default local DB,
- receive a deferred startup guard for heavy legacy DBs,
- switch DB explicitly,
- restart into a selected DB.

But the UI still under-explained three practical questions:

1. when default local DB is still the safer immediate choice;
2. when a single deliberate reconnect + restart is the right next step;
3. when heavy or legacy DBs may require backup or one longer restart.

## Bounded implementation

### Deferred startup guard

The startup guard now explains:

- reconnect should be intentional;
- the recommended path is one migrated DB, one switch, one restart;
- heavy DBs remain safer to reconnect only when explicitly needed;
- legacy DBs may spend one longer restart on backup + migration.

### Switch Database dialog

Reconnect guidance now distinguishes:

- `Default`
  - fastest/safest immediate path
  - reconnect heavy DB later if needed
- `Current-schema DB`
  - lowest-risk reconnect case
  - valid candidate for the next deliberate restart
- `Legacy-schema DB`
  - backup + migration may run before full UI startup
- `Heavy DB`
  - backup-first recommendation
  - avoid repeated switch/restart loops
- `Baseline (dev)`
  - intended as explicit reconnect into the large reference workspace

### First-run wizard DB step

The setup wizard DB step now mirrors the same restart contract:

- default DB is positioned as the local-first path;
- current-schema DB says `finish the wizard and restart once`;
- heavy DB warns that reconnect can take longer;
- baseline quick-pick is framed as an explicit reconnect choice for the large
  reference workspace.

## Outcome

This closes a bounded UX gap:

- operators now get clearer heavy-DB selection/restart guidance;
- reconnect remains explicit and intentional;
- no new backend, migration, or restart logic was introduced.
