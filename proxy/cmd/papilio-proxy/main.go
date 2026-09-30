// papilio-proxy is the operator-facing entry point for the Go node component.
// It intentionally has no HTTP listener; deploy-time reconciliation is wired
// through a least-privilege service account, not through the public bot.
package main

import (
	"fmt"
	"os"
)

const version = "dev"

func main() {
	if len(os.Args) < 2 {
		usage(os.Stderr)
		os.Exit(2)
	}

	switch os.Args[1] {
	case "help", "--help", "-h":
		usage(os.Stdout)
	case "version", "--version":
		fmt.Println(version)
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n\n", os.Args[1])
		usage(os.Stderr)
		os.Exit(2)
	}
}

func usage(output *os.File) {
	fmt.Fprintln(output, "Usage: papilio-proxy <help|version>")
}
