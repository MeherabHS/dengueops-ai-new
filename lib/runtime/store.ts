import { open, mkdir, lstat, realpath, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import type { RuntimeJobRecord, RuntimeWorkspaceMetadata } from "./contracts";
import { RuntimePublicError } from "./errors";
import type { WorkspacePaths } from "./paths";

async function rejectSymlink(target: string): Promise<void> {
  try {
    const stat = await lstat(target);
    if (stat.isSymbolicLink()) throw new RuntimePublicError("runtime_symlink_rejected", "storage", "Runtime storage cannot use symbolic links.", 500);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}

export async function initializeRuntimeRoot(runtimeRoot: string): Promise<void> {
  await mkdir(runtimeRoot, { recursive: true, mode: 0o700 });
  await rejectSymlink(runtimeRoot);
  const actual = await realpath(runtimeRoot);
  if (actual !== path.resolve(runtimeRoot)) {
    throw new RuntimePublicError("runtime_root_alias_rejected", "storage", "Runtime root must resolve directly to its configured path.", 500);
  }
  const workspaces = path.join(/* turbopackIgnore: true */ runtimeRoot, "workspaces");
  await mkdir(workspaces, { recursive: true, mode: 0o700 });
  await rejectSymlink(workspaces);
  for (const relative of ["jobs/pending", "jobs/running", "jobs/completed", "jobs/failed", "staging", "runs", "assessment-staging", "assessments", "outcome-staging", "forecast-outcomes", "degradation-staging", "degradation-evidence", "decisions", "assessment-decisions", "authorizations", "authorization-state", "deployments", "locks", "locks/decisions", "locks/authorizations"]) {
    await mkdir(path.join(runtimeRoot, relative), { recursive: true, mode: 0o700 });
  }
}

export async function createPendingJob(jobPath: string, job: RuntimeJobRecord): Promise<void> {
  await writeExclusive(jobPath, Buffer.from(`${JSON.stringify(job, null, 2)}\n`, "utf8"));
}

export async function createWorkspaceStartMarker(pathname: string, value: unknown): Promise<void> {
  await writeExclusive(pathname, Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8"));
}

export async function createWorkspace(paths: WorkspacePaths): Promise<void> {
  try {
    await mkdir(paths.root, { recursive: false, mode: 0o700 });
    await mkdir(paths.metadata, { mode: 0o700 });
    await mkdir(paths.originalInputs, { recursive: true, mode: 0o700 });
    await mkdir(paths.canonicalInputs, { recursive: true, mode: 0o700 });
    await mkdir(paths.logs, { mode: 0o700 });
  } catch (error) {
    await rm(paths.root, { recursive: true, force: true }).catch(() => undefined);
    throw new RuntimePublicError("workspace_creation_failed", "storage", "An isolated validation workspace could not be created.", 500, true);
  }
}

export async function writeExclusive(pathname: string, bytes: Buffer): Promise<void> {
  try {
    await writeFile(pathname, bytes, { flag: "wx", mode: 0o600 });
  } catch {
    throw new RuntimePublicError("workspace_file_write_failed", "storage", "An uploaded file could not be stored safely.", 500, true);
  }
}

export async function writeJsonAtomic(pathname: string, value: unknown): Promise<void> {
  const temporary = `${pathname}.${process.pid}.${Date.now()}.tmp`;
  const payload = `${JSON.stringify(value, null, 2)}\n`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(payload, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(temporary, pathname);
}

export async function writeWorkspaceMetadata(paths: WorkspacePaths, metadata: RuntimeWorkspaceMetadata): Promise<void> {
  await writeJsonAtomic(paths.workspaceMetadata, metadata);
}

export async function appendWorkspaceEvent(
  paths: WorkspacePaths,
  event: { timestamp: string; correlationId: string; workspaceId: string; eventType: string; metadata?: Record<string, unknown> },
): Promise<void> {
  const handle = await open(paths.events, "a", 0o600);
  try {
    await handle.write(`${JSON.stringify(event)}\n`);
    await handle.sync();
  } finally {
    await handle.close();
  }
}
