package main

import (
	"C"
	"fmt"
	"sync"
)
import (
	"os"
	"unsafe"

	"github.com/evanw/esbuild/pkg/api"
)

var (
	mutex    sync.Mutex
	contexts = make(map[int]*ESBuildContext)
	nextID   = 1
)

type ESBuildContext struct {
	Filename string
	Context  api.BuildContext
}

//export GetBuildContext
func GetBuildContext(
	rawFilename *C.char,
	rawNodeModulesPath *C.char,
	rawEnvironment *C.char,
	liveReloadPort C.int,
	isSSR C.int,
) C.int {
	/*
	 * liveReloadPort: 0 for no live reload
	 */
	mutex.Lock()
	defer mutex.Unlock()

	filename := C.GoString(rawFilename)
	nodeModulesPath := C.GoString(rawNodeModulesPath)
	environment := C.GoString(rawEnvironment)

	// If we already have the filename registered, return
	// the existing context ID.
	for id, context := range contexts {
		if context.Filename == filename {
			return C.int(id)
		}
	}

	buildOptions := api.BuildOptions{
		EntryPoints: []string{filename},
		Bundle:      true,
		Outfile:     filename + ".out",
		Sourcemap:   api.SourceMapExternal,
		Loader: map[string]api.Loader{
			".tsx": api.LoaderTSX,
			".jsx": api.LoaderJSX,
		},
		Define: map[string]string{
			"process.env.NODE_ENV":         fmt.Sprintf("\"%s\"", environment),
			"process.env.LIVE_RELOAD_PORT": fmt.Sprintf("%d", liveReloadPort),
		},
		NodePaths: []string{nodeModulesPath},
	}

	if isSSR == 1 {
		buildOptions.GlobalName = "SSR"
		buildOptions.Format = api.FormatIIFE
		buildOptions.Define["process.env.SSR_RENDERING"] = "true"
		buildOptions.Define["global"] = "window"
	} else {
		buildOptions.Format = api.FormatESModule
		buildOptions.Define["process.env.SSR_RENDERING"] = "false"
	}

	ctx, err := api.Context(buildOptions)
	if err != nil {
		// Log the error
		fmt.Println(err)
		os.Exit(1)
	}

	id := nextID
	nextID++
	contexts[id] = &ESBuildContext{
		Filename: filename,
		Context:  ctx,
	}
	fmt.Printf("Created context with ID %d for %s\n", id, filename)
	return C.int(id)
}

//export RebuildContext
func RebuildContext(id C.int) {
	mutex.Lock()

	context, exists := contexts[int(id)]
	if !exists {
		fmt.Printf("Context with ID %d does not exist\n", id)
		mutex.Unlock()
		return
	}
	mutex.Unlock()

	result := context.Context.Rebuild()
	if len(result.Errors) > 0 {
		// Log the errors
		fmt.Println(result.Errors)
		os.Exit(1)
	}

	// fmt.Printf("#### START ####\n")
	// fmt.Printf("Filename: %s (output: %d)\n", context.Filename, len(result.OutputFiles))

	for i := range result.OutputFiles {
		outputFile := result.OutputFiles[i]
		// fmt.Printf("------------\n")
		// fmt.Printf("Output file: %s\n", outputFile)
		// fmt.Printf("Path: %s\n", outputFile.Path)
		// fmt.Printf("Contents: %s\n", outputFile.Contents)

		// Write the output to a file
		err := os.WriteFile(outputFile.Path, outputFile.Contents, 0644)
		if err != nil {
			// Log the error
			fmt.Println(err)
			os.Exit(1)
		}
	}

	// fmt.Printf("#### DONE ####\n")
}

//export RebuildContexts
func RebuildContexts(ids *C.int, count C.int) {
	// Convert C array to Go slice
	goIDs := make([]int, count)
	for i := 0; i < int(count); i++ {
		goIDs[i] = int(*(*C.int)(unsafe.Pointer(uintptr(unsafe.Pointer(ids)) + uintptr(i)*unsafe.Sizeof(*ids))))
	}

	// Semaphore channel to limit concurrency
	var sem = make(chan struct{}, 25)

	var wg sync.WaitGroup
	for _, id := range goIDs {
		wg.Add(1)
		sem <- struct{}{} // Acquire semaphore

		// Launch a goroutine for each id
		go func(id int) {
			defer wg.Done()
			defer func() { <-sem }() // Release semaphore

			RebuildContext(C.int(id))
		}(id)
	}

	wg.Wait()
}

//export RemoveContext
func RemoveContext(id C.int) {
	mutex.Lock()
	defer mutex.Unlock()

	// Dispose of the ESBuild context to free up resources
	context, exists := contexts[int(id)]
	if !exists {
		fmt.Printf("Context with ID %d does not exist\n", id)
		return
	}

	context.Context.Dispose()
	delete(contexts, int(id))
}

func main() {}
