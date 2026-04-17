.PHONY : all prerequisites mosquitto linter libnyoci klee clean

all : prerequisites linter klee mosquitto

mosquitto : # Hard-coded test to make easier on my dev system.
	./make_diffs.sh -d ~/git/TARGETS/mosquitto -f with_tls

demo1 : # Demo for first container.
	./make_diffs.sh -d ../mosquitto -f with_tls

linter :
	g++ check_braces.cpp -o linter

klee:
	$(info Not yet implemented.)

libnyoci:
	sh ~/git/libnyoci/configure --enable-code-coverage --enable-embedded
	
prerequisites :
	sudo ../setup.sh

clean :
	rm -rf coverage_files* cov_files_* *.dot diff_* linter a.out *.html reports

reallyclean : clean
	rm -rf klee-*

democlean : clean
	rm -rf ../artifacts/mosquitto
	cp -r ../App/mosquitto ../artifacts/
	rm -rf ../artifacts/FFmpeg
	cp -r ../App/FFmpeg ../artifacts/
