package openvpn

import (
	"strings"
	"testing"
)

func TestManagementNotificationContracts(t *testing.T) {
	d := Decoder{MaxEnvironmentFields: 6}
	lines := []string{">INFO:management ready", ">CLIENT:CONNECT,0,2", ">CLIENT:ENV,common_name=profile-identity", ">CLIENT:ENV,password=private-not-retained", ">CLIENT:ENV,tls_serial_hex_0=12:34:AB", ">CLIENT:ENV,untrusted_ip6=2001:db8::7", ">CLIENT:ENV,END"}
	var event *Event
	for _, line := range lines {
		var err error
		event, err = d.Line(line)
		if err != nil {
			t.Fatal(err)
		}
	}
	if event == nil || event.ClientID != 0 || event.KeyID != 2 || event.Environment["common_name"] != "profile-identity" || len(event.Environment) != 3 || !d.Complete() {
		t.Fatal("incorrect atomic environment contract")
	}
	if _, exists := event.Environment["password"]; exists {
		t.Fatal("password entered event")
	}
	count, err := d.Line(">BYTECOUNT_CLI:0,41,59")
	if err != nil || count == nil || count.Received != 41 || count.Sent != 59 {
		t.Fatal("incorrect server counter direction")
	}
}

func TestMalformedManagementNotificationsFailClosed(t *testing.T) {
	cases := [][]string{
		{">CLIENT:ENV,END"}, {">CLIENT:CONNECT,1,1", ">CLIENT:REAUTH,1,2"},
		{">CLIENT:CONNECT,-1,2"}, {">CLIENT:CONNECT,4294967296,2"}, {">CLIENT:CONNECT,1,2,extra"},
		{">CLIENT:CONNECT,1,2", ">CLIENT:ENV,common_name=x", ">CLIENT:ENV,common_name=x"},
		{">CLIENT:CONNECT,1,2", ">CLIENT:ENV,password=x", ">CLIENT:ENV,password=x", ">CLIENT:ENV,password=x"},
		{">CLIENT:CONNECT,1,2", ">CLIENT:ENV,missing-value"}, {">BYTECOUNT_CLI:1,-1,0"},
		{">BYTECOUNT_CLI:1,9223372036854775807,1"}, {">BYTECOUNT_CLI:1,0,0,extra"},
		{">CLIENT:CONNECT,1,2\x00"}, {"ERROR:private-data"}, {">FATAL:private-data"},
	}
	for index, lines := range cases {
		d := Decoder{MaxEnvironmentFields: 2}
		failed := false
		for _, line := range lines {
			if _, err := d.Line(line); err != nil {
				failed = true
				if strings.Contains(err.Error(), "private-data") {
					t.Fatal("protocol diagnostic leaked private data")
				}
				break
			}
		}
		if !failed {
			t.Fatalf("invalid contract case %d was accepted", index)
		}
	}
	for _, serial := range []string{"", "0", "-AB", "0xAB", "AB:\nCD", "AB::CD", "A:BC"} {
		if _, valid := certificateSerial(serial); valid {
			t.Fatal("invalid certificate serial accepted")
		}
	}
	first, valid := certificateSerial("00:12:34:AB")
	second, otherValid := certificateSerial("1234ab")
	if !valid || !otherValid || first.Cmp(second) != 0 {
		t.Fatal("OpenVPN serial octets changed certificate identity")
	}
}
