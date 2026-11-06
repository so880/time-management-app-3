// ESLint（flat config）。Vite の React テンプレートと同じ構成：
// 未定義の変数（no-undef）・未使用の変数・React のフックの規則を確認する。実行：npm run lint
import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: { react: { version: 'detect' } },
    plugins: { react, 'react-hooks': reactHooks },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react/jsx-uses-vars': 'error',
      'react/jsx-uses-react': 'off',
      'react/jsx-key': 'error',
      'no-unused-vars': ['warn', { args: 'after-used', ignoreRestSiblings: true }],
      // 画面の文言の全角スペース（「　」）は意図したものなので、文字列・JSX の文言・コメントの中は対象外
      'no-irregular-whitespace': ['error', { skipStrings: true, skipTemplates: true, skipJSXText: true, skipComments: true }],
    },
  },
]
