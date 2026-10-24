//go:build linux

package main

import (
	"os"
	"os/exec"
	"strconv"
	"strings"
	"testing"
)

func TestUnexpectedManagedCoreExitStopsTheActualAgent(t *testing.T) {
	exerciseAgentExecutable(t, true, false, func(agent *exec.Cmd) {
		output, err := exec.Command("ps", "-o", "pid=", "--ppid", strconv.Itoa(agent.Process.Pid)).Output()
		if err != nil {
			t.Fatal(err)
		}
		ownedPID, err := strconv.Atoi(strings.TrimSpace(string(output)))
		if err != nil {
			t.Fatal("Agent did not own exactly one native core process.")
		}
		core, err := os.FindProcess(ownedPID)
		if err != nil {
			t.Fatal(err)
		}
		if err := core.Kill(); err != nil {
			t.Fatal(err)
		}
	})
}
