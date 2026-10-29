const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = __dirname;
const local = (name) => path.join(root, name);
process.env.PATH = local('toolchains/node-24.14.0') + path.delimiter + (process.env.PATH || '');
Object.assign(process.env, {
  DSH_HOME: local('harness-fast-home'),
  NPM_CONFIG_CACHE: local('harness-cache/npm'),
  NPM_CONFIG_USERCONFIG: local('harness-user/.npmrc'),
  APPDATA: local('harness-user/appdata'),
  LOCALAPPDATA: local('harness-user/localappdata'),
  USERPROFILE: local('harness-user'),
  HOMEDRIVE: 'F:',
  HOMEPATH: '\\STRATA\\harness-user',
  XDG_CACHE_HOME: local('harness-cache'),
  TEMP: local('tmp'),
  TMP: local('tmp'),
  DSH_TELEMETRY_MODE: 'DISABLED',
  STRATA_LOCAL_API_KEY: 'local-placeholder',
  NO_PROXY: '*'
});
for (const name of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']) delete process.env[name];
const entry = local('harness/node_modules/@deepseek-ai/dsh/lib/bin.js');
process.argv[1] = entry;
import(pathToFileURL(entry).href).then(({ runCli }) => runCli()).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

