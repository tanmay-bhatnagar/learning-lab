import js from '@eslint/js';
import { defineConfig } from 'eslint/config';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig(
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, tseslint.configs.recommended, reactHooks.configs.flat.recommended],
    languageOptions: { globals: globals.browser },
    rules: { 'no-empty': ['error', { allowEmptyCatch: false }] },
  },
  // Pre-existing violations; the frontend refactor removes these entries as it fixes them.
  {
    files: ['src/App.tsx'],
    rules: { 'react-hooks/refs': 'off', 'react-hooks/set-state-in-effect': 'off', 'no-empty': 'off' },
  },
  {
    files: ['tests/**/*.{js,mjs,ts,tsx}', '*.config.{js,ts}'],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: { globals: globals.node },
  },
);
