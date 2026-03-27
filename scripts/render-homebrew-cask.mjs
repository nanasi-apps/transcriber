#!/usr/bin/env node

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const TEMPLATE_PATH = fileURLToPath(
  new URL("../packaging/homebrew/transcriber.rb.template", import.meta.url),
);

function parseArgs(argv) {
  const options = {};

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith("--")) {
      throw new Error(`Unexpected argument: ${arg}`);
    }

    const key = arg.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for --${key}`);
    }

    options[key] = value;
    index += 1;
  }

  return options;
}

function required(options, key) {
  const value = options[key];
  if (!value) {
    throw new Error(`Missing required option --${key}`);
  }

  return value;
}

try {
  const options = parseArgs(process.argv.slice(2));
  const version = required(options, "version");
  const sha256 = required(options, "sha256");
  const repository = required(options, "repository");
  const artifact = required(options, "artifact");
  const output = options.output;

  const template = readFileSync(TEMPLATE_PATH, "utf8");
  const rendered = template
    .replaceAll("{{VERSION}}", version)
    .replaceAll("{{SHA256}}", sha256)
    .replaceAll("{{REPOSITORY}}", repository)
    .replaceAll("{{ARTIFACT_FILENAME}}", artifact);

  if (output) {
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, rendered, "utf8");
  } else {
    process.stdout.write(rendered);
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
