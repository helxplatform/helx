const path = require('path')
const ForkTsCheckerPlugin = require('fork-ts-checker-webpack-plugin')

module.exports = {
    entry: './src/index.ts',
    target: 'node',
    output: {
        filename: 'bundle.js',
        path: path.resolve(__dirname, 'dist')
    },
    resolve: {
        extensions: ['.ts', '.js']
    },
    module: {
        rules: [
            {
                test: /\.(js|ts)$/i,
                exclude: /node_modules/,
                use: {
                    loader: 'babel-loader',
                    options: {
                        presets: [
                            '@babel/preset-env',
                            '@babel/preset-typescript'
                        ],
                        plugins: [
                            [
                                '@babel/plugin-proposal-decorators',
                                { legacy: true }
                            ]
                        ]
                    }
                }
            }
        ]
    },
    plugins: [
        new ForkTsCheckerPlugin({
            async: false
        })
    ]
}