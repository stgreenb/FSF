// ForgeSteel data dump: serializes pseudo-data from the read-only
// forgesteel_repo checkout into fs_data/*.json consumed by the reverse
// converter (design D2). Nothing is written into the upstream repo.
//
// Build & run (from this directory):
//   ES=../../forgesteel_repo/node_modules/.bin/esbuild
//   $ES ../../forgesteel_repo/src/data/sourcebook-data.ts --bundle \
//       --platform=node --format=esm --log-level=error \
//       --tsconfig=../../forgesteel_repo/tsconfig.app.json \
//       --outfile=/tmp/opencode/fs-data-bundle.mjs
//   $ES dump.ts --bundle --platform=node --format=esm --log-level=error \
//       --outfile=/tmp/opencode/fs-dump.mjs
//   node /tmp/opencode/fs-dump.mjs --out ../../fs_data
//
// The first command bundles the checkout's own data modules, so esbuild must
// be pointed at its tsconfig.app.json to resolve the `@/*` path alias.

import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { SourcebookData } from '/tmp/opencode/fs-data-bundle.mjs';

const KINDS = [
	'ancestries', 'classes', 'subclasses', 'careers', 'cultures',
	'complications', 'perks', 'kits', 'items', 'titles', 'domains',
] as const;

const MEMBERSHIP_KINDS = [...KINDS, 'imbuements', 'domains', 'projects', 'titles'];

function argOut(): string {
	const i = process.argv.indexOf('--out');
	return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : 'fs_data';
}

/** Merge per-sourcebook element arrays into one id-keyed dict per kind. */
function collect() {
	const dicts: Record<string, Record<string, any>> = {};
	for (const kind of KINDS) dicts[kind] = {};
	const extras: Record<string, Record<string, any>> = {};
	for (const kind of MEMBERSHIP_KINDS)
		extras[kind] = dicts[kind] ?? (extras[kind] = {});

	const membership: Record<string, { name: string; members: string[] }> = {};
	const sourcebooks: any[] = [
		SourcebookData.core, SourcebookData.orden,
		SourcebookData.playtest, SourcebookData.ratcatcher,
	];

	for (const sb of sourcebooks) {
		if (!sb) continue;
		const settingId = sb.id === '' ? 'core' : sb.id;
		const entry = (membership[settingId] ??= { name: sb.name, members: [] });
		for (const kind of MEMBERSHIP_KINDS) {
			const list = (sb as any)[kind];
			if (!Array.isArray(list)) continue;
			for (const el of list) {
				if (el && typeof el.id === 'string' && typeof el.name === 'string') {
					extras[kind][el.id] = el;
					if (!entry.members.includes(el.id)) entry.members.push(el.id);
				}
			}
		}
	}

	// Subclasses only exist nested inside their parent classes; flatten them
	// into the dict and fold them into setting membership as well.
	for (const cls of Object.values(dicts.classes) as any[]) {
		for (const sub of cls?.subclasses ?? []) {
			if (sub && typeof sub.id === 'string') dicts.subclasses[sub.id] = sub;
		}
	}
	for (const entry of Object.values(membership)) {
		for (const clsId of entry.members.filter((id) => id.startsWith('class-'))) {
			const cls = dicts.classes[clsId];
			for (const sub of cls?.subclasses ?? []) {
				if (!entry.members.includes(sub.id)) entry.members.push(sub.id);
			}
		}
	}
	return { dicts, membership };
}

/** Yield every Feature object in a container tree (levels, nesting, choices). */
function* featuresOf(node: any): Generator<any> {
	if (!node || typeof node !== 'object') return;
	if (Array.isArray(node)) {
		for (const item of node) yield* featuresOf(item);
		return;
	}
	if (typeof node.type === 'string') yield node;
	if (node.data?.features) yield* featuresOf(node.data.features);
	if (Array.isArray(node.data?.options))
		for (const opt of node.data.options) yield* featuresOf(opt?.feature);
	if (Array.isArray(node.featuresByLevel))
		for (const lvl of node.featuresByLevel) yield* featuresOf(lvl?.features);
	if (Array.isArray(node.features)) yield* featuresOf(node.features);
	if (Array.isArray(node.subclasses))
		for (const sub of node.subclasses) yield* featuresOf(sub);
}

/** kit id -> granting Kit features (container, subclass, feature, level). */
function buildKitGrants(dicts: Record<string, Record<string, any>>) {
	const seen = new Set<string>();
	const grants: Record<string, any[]> = {};
	for (const kit of Object.keys(dicts.kits)) grants[kit] = [];
	const kitType = (id: string) => (dicts.kits[id] as any)?.type ?? '';
	const typeOf = (kitId: string) => kitType(kitId);

	for (const cls of Object.values(dicts.classes) as any[]) {
		const holders: { holder: any; subclassId: string | null }[] =
			[{ holder: cls, subclassId: null },
			...(cls?.subclasses ?? []).map((s: any) => ({ holder: s, subclassId: s.id }))];
		for (const { holder, subclassId } of holders) {
			for (const lvl of holder?.featuresByLevel ?? []) {
				for (const f of featuresOf(lvl?.features)) {
					if (f?.type !== 'Kit') continue;
					const types: string[] =
						f.data?.types?.length ? f.data.types : [''];
					for (const kitId of Object.keys(dicts.kits)) {
						if (!types.includes(typeOf(kitId))) continue;
						const key = `${kitId}|${cls.id}|${subclassId}|${f.id}`;
						if (seen.has(key)) continue;
						seen.add(key);
						grants[kitId].push({
							containerId: cls.id, subclassId,
							featureId: f.id, level: lvl?.level ?? null,
						});
					}
				}
			}
		}
	}
	return grants;
}

function main() {
	const outDir = argOut();
	mkdirSync(outDir, { recursive: true });
	const { dicts, membership } = collect();

	const counts: Record<string, number> = {};
	for (const kind of KINDS) {
		const sorted: Record<string, any> = {};
		for (const id of Object.keys(dicts[kind]).sort()) sorted[id] = dicts[kind][id];
		writeFileSync(join(outDir, `${kind}.json`), JSON.stringify(sorted, null, 2) + '\n');
		counts[kind] = Object.keys(sorted).length;
	}

	const kitGrants = buildKitGrants(dicts);
	writeFileSync(join(outDir, 'kit_grants.json'), JSON.stringify(kitGrants, null, 2) + '\n');
	counts.kit_grants_with_grants = Object.values(kitGrants).filter((g) => g.length).length;

	const sortedMembership: Record<string, any> = {};
	for (const id of Object.keys(membership).sort()) {
		const m = membership[id];
		sortedMembership[id] = { name: m.name, members: m.members.sort() };
	}
	writeFileSync(join(outDir, 'setting_membership.json'), JSON.stringify(sortedMembership, null, 2) + '\n');
	counts.settings = Object.keys(sortedMembership).length;

	console.log('dumped:', JSON.stringify(counts));
}

main();
