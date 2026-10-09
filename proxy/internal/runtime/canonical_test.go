package runtime

import (
	"bytes"
	"testing"
)

func TestCanonicalCredentialUnicodeNullAndLiteralEscape(t *testing.T) {
	source := []byte(`{"z":null,"password":"<>&\u2028\\u2028\u2029","identity":"پویا"}`)
	expected := []byte("{\"identity\":\"پویا\",\"password\":\"<>&\u2028\\\\u2028\u2029\",\"z\":null}")
	actual, err := canonicalJSON(source)
	if err != nil || !bytes.Equal(actual, expected) {
		t.Fatal("canonical UTF8/null/literal escape differs")
	}
}
