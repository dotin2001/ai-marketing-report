#!/usr/bin/env node

import { main } from "./ai-local/cli.mjs";

const outcome = await main(process.argv.slice(2));
process.exitCode = outcome.exitCode;
